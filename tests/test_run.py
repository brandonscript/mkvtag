import sys


def test_run():
    from mkvtag.run import main

    # sys.argv.append("./mkvtag")
    sys.argv.append("/Volumes/media/Downloads/#converted")
    sys.argv.append("-l=5")

    main()
