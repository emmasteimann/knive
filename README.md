Knive - Cuts live
=================

Knive is an audio/video streaming solution with it´s current main focus on [HTTP Live Streaming](http://tools.ietf.org/html/draft-pantos-http-live-streaming-08). As a fallback mp3 streaming (as seen in [icecast](http://en.wikipedia.org/wiki/Icecast) and others) is supported.
While the encoding, muxing and cutting is done with [ffmpeg](http://en.wikipedia.org/wiki/Ffmpeg) most of the software is written in [python/twisted](http://twistedmatrix.com/trac/).

The author(s) try to integrate ideas and formats by the [podlove project](http://www.podlove.org).


Here are two typical scenarios where you might want to use knive.

### HTTP Live Streaming support
Knive can be the software you want to use to support iOS devices for audio and video streaming. You already have a working RTMP server to stream live content to your visitors? Install knive and iOS devices can enjoy your content while preserving battery life and minimizing network usage.


### Streaming & Instant publishing
Knive is developed with the needs of podcasters in mind. While it is possible to stream audio only streams to iOS devices it will drain battery and won't work for video. Also, with HTTP Live Streaming your audience will be able to consume your show while still recording. From the beginning (timeshift).
Your content will be available to your audience while still recording.


Features
--------

* Support for Blackmagic ATEM TV Studio (via atemClient)
* Files as input(Any encoding/container/protocol accepted by ffmpeg, h.264, ogg)
* Adobe Flash Media Encoder support - Capture your content and send it to the knive backend
* HTTP Live Streaming with ReLive/Timeshift capabilities (video on demand the second you start recording)
* Multiple channels/streams with one backend. (Hosting a conference? Having content from more than one source at the same time?)



Status
------
The project was started in december 2011 and is currently an early alpha. While the code available on github is working it's not anywhere near for production use.
So far the following simple workflow is working:
Blackmagic ATEM Studio Client -> atemClient -> Internet -> Knive Backend -> HTTP Live Stream in various qualities.

In the next weeks/month the following features will be added:

* Adobe Flash Media Encode as input source. Proof of concept code available. Integration with knive has to be done.
* Admin Interface
* MP3 Stream Fallback


