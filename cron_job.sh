set -e
cd /home/mcgibbon/Documents/flamingo_website/FLAMINGO
if [ -f src/pages/papers.html ]; then
    rm src/pages/papers.html
fi
/home/mcgibbon/Documents/flamingo_website/venv/bin/python generate_publication_list.py > cron_job.out
/home/mcgibbon/Documents/flamingo_website/venv/bin/python make_webpage.py >> cron_job.out

rm -r /disks/web1/flamingo/*
cp -r build/* /disks/web1/flamingo/
rm -r build
# Should copy to somewhere else on disk, then do a mv

