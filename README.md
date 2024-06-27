# mkvtag
 
## Description

This is a simple Docker container wrapper for `mkvpropedit --add-track-statistics-tags` command, which adds track statistics tags to a Matroska file like average bitrate, number of frames, etc. This container, when run, will watch a directory for new files and automatically add the track statistics tags to them.

Primarily, this is useful for [HandBrake](https://handbrake.fr) encoded files, which do not have these tags by default, for example:

```bash
# Before
Video
Format                                   : HEVC
Format/Info                              : High Efficiency Video Coding
Format profile                           : Main 10@L4@Main
Codec ID                                 : V_MPEGH/ISO/HEVC
Duration                                 : 3 min 8 s
Width                                    : 1 920 pixels
Height                                   : 1 080 pixels
Display aspect ratio                     : 2.35:1
Frame rate mode                          : Constant
Frame rate                               : 23.976 (24000/1001) FPS
Color space                              : YUV
Chroma subsampling                       : 4:2:0
Bit depth                                : 10 bits
Color primaries                          : BT.709
Transfer characteristics                 : BT.709
Matrix coefficients                      : BT.709
```

```bash
# After
Video
Format                                   : HEVC
Format/Info                              : High Efficiency Video Coding
Format profile                           : Main 10@L4@Main
Codec ID                                 : V_MPEGH/ISO/HEVC
Duration                                 : 3 min 8 s
Bit rate                                 : 6 060 kb/s # Added!
Width                                    : 1 920 pixels
Height                                   : 1 080 pixels
Display aspect ratio                     : 2.35:1
Frame rate mode                          : Constant
Frame rate                               : 23.976 (24000/1001) FPS
Color space                              : YUV
Chroma subsampling                       : 4:2:0
Bit depth                                : 10 bits
Bits/(Pixel*Frame)                       : 0.122 # Added!
Stream size                              : 5.64 GiB (56%) # Added!
Color primaries                          : BT.709
Transfer characteristics                 : BT.709
Matrix coefficients                      : BT.709
```

## Usage

(Make sure you have Docker installed on your system)

1. Clone this repository and `cd` into it: 
  
    ```
    git clone https://github.com/brandonscript/mkvtag.git && cd mkvtag
    ```

2. Build the Docker image: 

    With the provided script: 

    ```
    ./docker_build.sh "<path-to-your-converted-dir>"
    ```

    or manually: 

    ```
    docker build -t mkvtag .
    docker run -v "<your-converted-dir>":/watchdir \
      --restart unless-stopped \ 
      --name mkvtag -d mkvtag
    ```

3. That's it! The container will now watch the directory you specified for new files and automatically add the track statistics tags to them. To check the logs, run: 

    ```
    docker logs -f mkvtag
    ```

    You can also inspect the `mkvtag.json` file in the directory you specified to see the status of the files that have been processed.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.