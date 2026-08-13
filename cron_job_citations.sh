set -e
cd /home/mcgibbon/Documents/flamingo_website/FLAMINGO

/home/mcgibbon/Documents/flamingo_website/venv/bin/python find_uncatalogued_citations.py > cron_job_citations.out
