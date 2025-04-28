import requests
import html
from urllib.parse import urlencode

# Place your ADS API token in a file with suitable permissions
with open('token', 'r') as file:
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
except KeyError:
    print(results.json())
    raise KeyError
bibcodes += results.json()['documents']

# Pagination
while len(bibcodes) < n_bibcodes_in_library:
    query = f"https://api.adsabs.harvard.edu/v1/biblib/libraries/{library}?rows={rows}&start={len(bibcodes)}"
    results = requests.get(query, headers=headers)
    bibcodes += results.json()['documents']


def format_paper_data(result):
    '''
    Takes in the ADS OpenAPI response and extracts the information
    we want to display on the webpage.
    '''

    # Generate author list
    if len(result['author']) < 20:
        author = ''
        for a in result['author']:
            last, first = a.split(', ')
            author += first + ' ' + last + ', '
        author = author[:-2] # Remove trailing ', '
    else:
        last, first = result['author'][0].split(', ')
        author = first + ' ' + last + ' et al.'

    # Determine arxiv identifier
    arxiv_identifier = ''
    for identifier in result['identifier']:
        if 'arXiv:' in identifier:
            arxiv_identifier = identifier.replace('arXiv:', '')
    if arxiv_identifier == '':
        print(f'Arxiv link not found for: {result["identifier"][0]}')
        exit()

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
        html.escape(result['title'][0]), # Escape troublesome characters
        author,
        f'https://ui.adsabs.harvard.edu/abs/{result["identifier"][0]}',
        f'https://arxiv.org/abs/{arxiv_identifier}',
        journal,
        result['year'],
    )

# Use the API to get information for the papers
papers = []
rows = 5  # How many papers to include for each API call
for i in range(0, len(bibcodes), rows):
    bibcode_query = f'bibcode:{bibcodes[i]}'
    for j in range(1, rows):
        if i + j < len(bibcodes):
            bibcode_query += f' OR bibcode:{bibcodes[i+j]}'
    query_parameters = urlencode({"q": bibcode_query, 'fl': 'title,author,pubdate,date,pub,identifier,year'})
    query = "https://api.adsabs.harvard.edu/v1/search/query?{}".format(query_parameters)
    results = requests.get(query, headers=headers)

    for result in results.json()['response']['docs']:
        print(f'Processing paper: {len(papers)+1}/{len(bibcodes)}')
        data = format_paper_data(dict(result))
        papers.append(data)

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
        file.write(f'<a href="{paper[2]}" class="active text-decoration-none">ADS</a>, ')
        file.write(f'<a href="{paper[3]}" class="active text-decoration-none">arXiv</a></p></li>\n')

    file.write('</ol>\n')

