import os
import sys
import requests
import html
import yaml
from urllib.parse import urlencode

# Cache mapping normalised paper title -> arxiv identifier. Used as a
# fallback for the case where a paper's arxiv identifier is
# temporarily missing from its ADS record, which happens for a few days
# around when the paper gets accepted by a journal.
ARXIV_ID_CACHE_PATH = 'arxiv_id_cache.yml'


def normalize_title(title):
    # Truncate to 122 characters, the maximum size of a PyYAML key
    return ''.join(title.split()).lower()[:122]


def load_arxiv_id_cache():
    if not os.path.exists(ARXIV_ID_CACHE_PATH):
        return {}
    with open(ARXIV_ID_CACHE_PATH, 'r') as file:
        cache = yaml.safe_load(file)
    return cache or {}


def save_arxiv_id_cache(cache):
    with open(ARXIV_ID_CACHE_PATH, 'w') as file:
        yaml.safe_dump(cache, file, sort_keys=True, allow_unicode=True)


# Place your ADS API token in a file with suitable permissions
with open('ADS_token', 'r') as file:
    token = file.read().rstrip()

# Identifier of the FLAMINGO ADS library
library = 'PU1J-aufRMujuhkIIRyxzA'

# Get list of papers in the library
print('Querying ADS library for paper list')
bibcodes = []
headers = {'Authorization': 'Bearer ' + token}
rows = 40

# Initial query, get total number of papers
query = f"https://api.adsabs.harvard.edu/v1/biblib/libraries/{library}?rows={rows}&start={len(bibcodes)}"
results = requests.get(query, headers=headers)
try:
    n_bibcodes_in_library = results.json()['metadata']['num_documents']
    bibcodes += results.json()['documents']
except (KeyError, requests.exceptions.JSONDecodeError):
    print(f'Unexpected response from ADS, status code: {results.status_code}, body: {results.text}', file=sys.stderr)
    raise

# Pagination
while len(bibcodes) < n_bibcodes_in_library:
    query = f"https://api.adsabs.harvard.edu/v1/biblib/libraries/{library}?rows={rows}&start={len(bibcodes)}"
    results = requests.get(query, headers=headers)
    try:
        documents = results.json()['documents']
    except (KeyError, requests.exceptions.JSONDecodeError):
        print(f'Unexpected response from ADS, status code: {results.status_code}, body: {results.text}', file=sys.stderr)
        raise
    if not documents:
        # ADS counts every bibcode in the library, but only serves those which
        # still resolve to a record. If one has been merged or deleted the two
        # numbers disagree and we would loop forever waiting for the rest.
        print(f'ADS reports {n_bibcodes_in_library} papers in the library but only served {len(bibcodes)}, '
              'probably an unmatched or merged record')
        break
    bibcodes += documents


def format_paper_data(result, arxiv_id_cache):
    '''
    Takes in the ADS OpenAPI response and extracts the information
    we want to display on the webpage.
    '''

    title = result['title'][0]
    normalized_title = normalize_title(title)

    # Determine arxiv identifier
    arxiv_identifier = ''
    for identifier in result['identifier']:
        if 'arXiv:' in identifier:
            arxiv_identifier = identifier.replace('arXiv:', '')
    if arxiv_identifier == '':
        # The arxiv identifier can be temporarily removed from a paper's ADS
        # record around when it gets accepted by a journal, before ADS
        # relinks it a few days later. Fall back to the id we cached from
        # the last time this paper resolved successfully.
        if normalized_title in arxiv_id_cache:
            arxiv_identifier = arxiv_id_cache[normalized_title]
            print(f'Arxiv link not found for: {result["identifier"][0]}, using cached id {arxiv_identifier}', file=sys.stderr)
        else:
            print(f'Arxiv link not found for: {result["identifier"][0]}, no cached id available', file=sys.stderr)
            arxiv_identifier = '99999'
    else:
        arxiv_id_cache[normalized_title] = arxiv_identifier

    # Generate author list (list all authors for the main reference papers)
    if (len(result['author']) < 20) or (arxiv_identifier in ['2306.04024', '2306.05492']):
        author = ''
        for a in result['author']:
            last, first = a.split(', ')
            author += first + ' ' + last + ', '
        author = author[:-2] # Remove trailing ', '
    else:
        last, first = result['author'][0].split(', ')
        author = first + ' ' + last + ' et al.'

    # Shorter name for journal
    journal = {
            'arXiv e-prints': 'arxiv',
            'Monthly Notices of the Royal Astronomical Society': 'MNRAS',
            'The Astrophysical Journal': 'ApJ',
    }.get(result['pub'], '')
    if journal == '':
        print('Journal not recognised:', result['pub'])
        journal = result['pub']

    # Return parsed data
    return (
        html.escape(title), # Escape troublesome characters
        author,
        f'https://ui.adsabs.harvard.edu/abs/{result["identifier"][0]}',
        f'https://arxiv.org/abs/{arxiv_identifier}',
        journal,
        result['year'],
    )

arxiv_id_cache = load_arxiv_id_cache()

# Use the API to get information for the papers
papers = []
rows = 100  # How many papers to include for each API call
for i in range(0, len(bibcodes), rows):
    bibcode_query = f'bibcode:{bibcodes[i]}'
    for j in range(1, rows):
        if i + j < len(bibcodes):
            bibcode_query += f' OR bibcode:{bibcodes[i+j]}'
    # rows must be passed to ADS, without it ADS returns its default of 10 documents,
    # silently dropping the rest of the batch.
    query_parameters = urlencode({"q": bibcode_query, 'fl': 'title,author,pubdate,date,pub,identifier,year', 'rows': rows})
    query = "https://api.adsabs.harvard.edu/v1/search/query?{}".format(query_parameters)
    results = requests.get(query, headers=headers)

    for result in results.json()['response']['docs']:
        print(f'Processing paper: {len(papers)+1}/{len(bibcodes)}')
        data = format_paper_data(dict(result), arxiv_id_cache)
        papers.append(data)

save_arxiv_id_cache(arxiv_id_cache)

# Sort based on arxiv identifier
papers = sorted(papers, key=lambda d: d[3])

# Write basic html file, which will be formatter with make_webpage.py
with open('src/pages/papers.html', 'w') as file:
    file.write('<h1>FLAMINGO publications</h1>\n')
    file.write('This page contains a list of publications submitted to arXiv which make use of the FLAMINGO simulations. The papers are listed in chronological order based on when they were uploaded to arXiv. Please let us know if we have missed your paper!\n\n')

    file.write('<ol>\n')

    for paper in papers:
        file.write(f'<li><p><h5>{paper[0]}</h5>\n')
        file.write(f'<i>{paper[1]}</i><br>\n')
        file.write(f'{paper[4]} ({paper[5]}), ')
        file.write(f'<a href="{paper[2]}" class="active text-decoration-none">ADS</a>')
        if paper[3] != 'https://arxiv.org/abs/99999':
            # Skip arxiv if an identifier cannot be found
            file.write(f', <a href="{paper[3]}" class="active text-decoration-none">arXiv</a>')
        file.write('</p></li>\n')

    file.write('</ol>\n')
