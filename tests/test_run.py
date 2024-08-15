import sys


def test_run():
    from mkvtag.run import main

    # sys.argv.append("./mkvtag")
    sys.argv.append("./tests/fixtures")
    # sys.argv.append("/Volumes/media/Downloads/#converted")
    sys.argv.append("-l=5")
    sys.argv.append("--log=./mkvtag/mkvtag.json")
    sys.argv.append(r"-x [._-]*(remux|\bavc|vc-1|x264)")

    main()
