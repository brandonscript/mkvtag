import sys


def test_run():
    from mkvtag.run import main

    sys.argv.append("./mkvtag")

    main()
