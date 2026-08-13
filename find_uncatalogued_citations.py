'''
Finds papers which cite the FLAMINGO data release paper but which are not
yet in the FLAMINGO ADS library.

The report of missing papers is written to stderr, and everything else
(warnings which do not need acting on) to stdout. This is so that cron can
send the report by email while the warnings go to the log file. Note this is
the opposite way round to generate_publication_list.py, where stdout is
routine progress and stderr is for problems.
'''
import sys
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

# Papers whose citations we track. These are given as ADS identifiers
TRACKED_IDENTIFIERS = [
    'arXiv:2604.24324',  # Helly et al., the FLAMINGO data release paper
]

# Papers which cite a tracked paper but which we have decided do not belong
# in the library, e.g. those which only mention FLAMINGO in passing without
# using the data. Add an identifier here to stop it being reported.
# Any identifier of the paper works (bibcode, arxiv id, or doi), but
# the arxiv id is the most stable choice.
IGNORED_IDENTIFIERS = [
    'arXiv:2603.22670 ',
    'arXiv:2606.19452',
    'arXiv:2607.01175',
]

# Papers are only reported once they have been on arxiv for this long. This
# gives us a chance to add a paper to the library ourselves before it gets
# flagged, and avoids reporting a paper on the same day it appears.
MINIMUM_AGE = timedelta(days=7)

# Identifier of the FLAMINGO ADS library
LIBRARY = 'PU1J-aufRMujuhkIIRyxzA'

# Number of records to request per API call
ROWS = 100


def get_json(query, headers):
    results = requests.get(query, headers=headers)
    try:
        return results.json()
    except requests.exceptions.JSONDecodeError:
        print(f'Unexpected response from ADS, status code: {results.status_code}, body: {results.text}', file=sys.stderr)
        raise


def get_library_bibcodes(headers):
    '''
    Returns the bibcodes of every paper in the FLAMINGO ADS library.
    '''
    bibcodes = []
    n_bibcodes_in_library = None
    while (n_bibcodes_in_library is None) or (len(bibcodes) < n_bibcodes_in_library):
        query = f'https://api.adsabs.harvard.edu/v1/biblib/libraries/{LIBRARY}?rows={ROWS}&start={len(bibcodes)}'
        response = get_json(query, headers)
        try:
            n_bibcodes_in_library = response['metadata']['num_documents']
            documents = response['documents']
        except KeyError:
            print(f'Unexpected response from ADS: {response}', file=sys.stderr)
            raise
        if not documents:
            # ADS counts every bibcode in the library, but only serves those
            # which still resolve to a record. If one has been merged or
            # deleted the two numbers disagree and we would loop forever
            # waiting for the rest.
            print(f'ADS reports {n_bibcodes_in_library} papers in the library but only served '
                  f'{len(bibcodes)}, probably an unmatched or merged record')
            break
        bibcodes += documents
    return bibcodes


def search(query_string, fields, headers):
    '''
    Runs an ADS search, handling pagination. Returns the list of documents.
    '''
    docs = []
    n_found = None
    while (n_found is None) or (len(docs) < n_found):
        query_parameters = urlencode({
            'q': query_string,
            'fl': ','.join(fields),
            'rows': ROWS,
            'start': len(docs),
        })
        response = get_json(f'https://api.adsabs.harvard.edu/v1/search/query?{query_parameters}', headers)
        try:
            n_found = response['response']['numFound']
            page = response['response']['docs']
        except KeyError:
            print(f'Unexpected response from ADS: {response}', file=sys.stderr)
            raise
        if not page:
            # Guard against looping forever if ADS stops returning records
            break
        docs += page
    return docs


def get_library_identifiers(bibcodes, headers):
    '''
    Returns the set of all identifiers (bibcodes, alternate bibcodes, arxiv
    ids, dois) of the papers in the library. We compare on the full set of
    identifiers rather than on bibcodes alone, since the library may hold the
    arxiv bibcode of a paper which has since been published under a different
    bibcode.
    '''
    identifiers = set(bibcodes)
    for i in range(0, len(bibcodes), ROWS):
        batch = bibcodes[i:i+ROWS]
        query_string = 'bibcode:(' + ' OR '.join(batch) + ')'
        for doc in search(query_string, ['bibcode', 'identifier'], headers):
            identifiers.add(doc['bibcode'])
            identifiers |= set(doc.get('identifier', []))
    return identifiers


def get_entry_date(doc):
    '''
    Returns the date the paper's record entered ADS, which for a paper with
    an arxiv posting is the date it appeared on arxiv. Returns None if the
    date is missing or cannot be parsed, in which case we report the paper
    rather than risk silently hiding it.
    '''
    entry_date = doc.get('entry_date', '')
    if entry_date == '':
        return None
    try:
        # Format is e.g. 2026-04-28T00:00:00Z
        return datetime.strptime(entry_date, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        print(f'Could not parse entry date "{entry_date}" for {doc["bibcode"]}')
        return None


def get_arxiv_identifier(doc):
    arxiv_identifier = ''
    for identifier in doc.get('identifier', []):
        if 'arXiv:' in identifier:
            arxiv_identifier = identifier.replace('arXiv:', '')
    return arxiv_identifier


def get_arxiv_month_end(doc):
    '''
    Returns the last day of the month in which the paper was posted to arxiv,
    worked out from the YYMM part of its arxiv identifier. This is the latest
    date the paper can possibly have appeared, so using it means we never
    report a paper as being older than it really is. Returns None for papers
    with no arxiv identifier, or with an old style one such as astro-ph/0601001.
    '''
    arxiv_identifier = get_arxiv_identifier(doc)
    if ('.' not in arxiv_identifier) or (len(arxiv_identifier.split('.')[0]) != 4):
        return None
    year_month = arxiv_identifier.split('.')[0]
    try:
        year = 2000 + int(year_month[:2])
        month = int(year_month[2:])
        # The last day of a month is the day before the first of the next
        first_of_next_month = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
    except ValueError:
        return None
    return first_of_next_month - timedelta(days=1)


def get_paper_date(doc):
    '''
    Returns our best estimate of when the paper first became available.

    The ADS entry date is not enough on its own: when a paper is accepted by
    a journal its record picks up the entry date of the published version,
    which can be months after it appeared on arxiv. So we also derive a date
    from the arxiv identifier and take whichever is earlier. Returns None if
    neither date is available, in which case we report the paper rather than
    risk silently hiding it.
    '''
    dates = [date for date in (get_entry_date(doc), get_arxiv_month_end(doc)) if date is not None]
    if not dates:
        return None
    return min(dates)


def format_paper(doc):
    title = doc.get('title', ['(no title)'])[0]
    authors = doc.get('author', [])
    if len(authors) == 0:
        author = '(no authors)'
    elif len(authors) == 1:
        author = authors[0]
    else:
        author = authors[0] + ' et al.'

    arxiv_identifier = get_arxiv_identifier(doc)

    paper_date = get_paper_date(doc)
    appeared = 'unknown date' if paper_date is None else paper_date.strftime('%Y-%m-%d')

    lines = [
        f'  {title}',
        f'  {author} ({doc.get("year", "")}), {doc.get("pub", "")}',
        f'  Appeared no later than: {appeared}',
        f'  https://ui.adsabs.harvard.edu/abs/{doc["bibcode"]}/abstract',
    ]
    if arxiv_identifier != '':
        lines.append(f'  https://arxiv.org/abs/{arxiv_identifier}')
    return '\n'.join(lines)


def main():
    # Place your ADS API token in a file with suitable permissions
    with open('ADS_token', 'r') as file:
        token = file.read().rstrip()
    headers = {'Authorization': 'Bearer ' + token}

    library_identifiers = get_library_identifiers(get_library_bibcodes(headers), headers)
    # Strip whitespace so a stray space in the list above does not stop a
    # paper being ignored
    ignored_identifiers = {identifier.strip() for identifier in IGNORED_IDENTIFIERS}
    cutoff = datetime.now(timezone.utc) - MINIMUM_AGE

    fields = ['bibcode', 'identifier', 'title', 'author', 'year', 'pub', 'entry_date']
    missing = {}
    for tracked in TRACKED_IDENTIFIERS:
        query_string = f'citations(identifier:"{tracked}")'
        for doc in search(query_string, fields, headers):
            doc_identifiers = set(doc.get('identifier', [])) | {doc['bibcode']}
            if doc_identifiers & library_identifiers:
                continue
            if doc_identifiers & ignored_identifiers:
                continue
            # Only report papers which are on arxiv, since the library lists
            # publications submitted to arxiv
            if get_arxiv_identifier(doc) == '':
                continue
            # Give ourselves a chance to add recent papers before flagging them
            paper_date = get_paper_date(doc)
            if (paper_date is not None) and (paper_date > cutoff):
                continue
            # A paper citing several tracked papers should only be listed once
            missing[doc['bibcode']] = doc

    if not missing:
        return

    # Written to stderr so that cron emails it, see the note at the top
    print('The following papers cite a FLAMINGO paper but are not in the FLAMINGO ADS library:', file=sys.stderr)
    print(f'Library: https://ui.adsabs.harvard.edu/user/libraries/{LIBRARY}\n', file=sys.stderr)
    for doc in missing.values():
        print(format_paper(doc), file=sys.stderr)
        print(file=sys.stderr)


if __name__ == '__main__':
    main()
