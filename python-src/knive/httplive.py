# httplive.py
# Copyright (c) 2012 Thorsten Philipp <kyrios@kyri0s.de>

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
import os
import tempfile
import shutil
import re
import logging
import datetime
import time
import string
import random
import sha

from twisted.internet       import reactor
from zope.interface import implements
from kninterfaces           import IKNRecorder
from collections    import deque

from foundation import KNDistributor, KNOutlet, KNProcessProtocol
from ffmpeg     import FFMpeg
from channel    import Channel
# from exceptions import 
import knive

class HTTPLiveStream(KNDistributor):
    """
    A HTTPLiveStream accepts mpeg-ts streams (optionally) reencodes the data to (optionally) various qualities and cuts them in pieces.

    The result of this are small .ts files of several seconds duration. The HTTPLiveStream creates a playlist over the created .ts files.
    The .ts segments and playlist are then typically stored on a webserver. Clients supporting HTTPLiveStream specification can then display
    the stream. See http://tools.ietf.org/html/draft-pantos-http-live-streaming for a full specification.

    Extends :class:`KNDistributor`
    """
    implements(IKNRecorder)
    
    
    def __init__(self,name='Unknown',destdir=None,channel=None,segmentServer=None,lastIndex=1):
        """
        Kwargs:
        name: Name of the stream. (Set by channel.name if not set and channel available)
        destdir: The location of resulting output files
        channel: The :mod:`channel` object this stream belongs to.
        publishURL: The URL where the stream will be acessible to users.
        lastIndex: The "biggest" index currently used by all variant streams. 
        """
        self.name = name
        self.channel = channel
        """name of the stream"""
        if channel.name and name == 'Unknown':
            self.name = channel.name
        super(HTTPLiveStream, self).__init__(name=self.name) # Call this after we have a name.

        self.segmentServer = segmentServer
        """The URL where ts files will be available at."""

        self.lastIndex = lastIndex
        """This is the index of the first index in a resulting new M3U8 file. 

        It is where a previous segmenter for the same stream left the work. For Livestreams
        it's important to save it since the stream may be interrupted. Also, the same
        moment in time should result in the same index for every VariantStream to make
        adaptive Quality work. For the case that a VariantStream dies it shall restart with
        the biggest StartIndex at that given time (over all other variant streams). Therefore
        each variantStream updates this value.
        """


        self.outlets = []
        """List of available :class:`HTTPLiveVariantStream` objects."""


        self._destdir = None
        if not destdir:
            raise Exception('destdir can not be none.')
        self.setDestdir(destdir)


        self.segmentIndex = {}
        """Stores random numbers per segment"""

        self.episode = None

    def createQuality(self,name,config,ffmpegbin=None):
        """
        Create a new :class:`HTTPLiveVariantStream` object and add it to self.qualities.

        Args:
            name: Give this Quality a name.

            config: A valid :class:`configobj.ConfigObj` for setup of this quality.

        Returns:
            The created :class:`HTTPLiveVariantStream`
        """

        self.log.info('Creating new HTTPLiveVariantStream: %s' % name)
        variantDir = self._destdir + os.path.sep + name
        httpliveStreamvariant = HTTPLiveVariantStream(name,config,ffmpegbin=ffmpegbin,destdir = variantDir)
        self.addQuality(httpliveStreamvariant)
        return httpliveStreamvariant

        
    def addQuality(self,quality):
        """Add a :class:`HTTPLiveVariantStream` object to self."""
        # TODO: Fix/Check behaviour when already running. What happens?
        self.addOutlet(quality)

    def removeQuality(self,quality):
        """Remove a quality from the stream. This is tricky (?) when the stream is running"""
        self.removeOutlet(quality)
        
   
    def setLastIndex(self,lastIndex):
        """Update self.lastIndex if it's larger than the current value. This is called by variant streams everytime they write a segment."""
        if (lastIndex > self.lastIndex):
            self.lastIndex = lastIndex

    def setDestdir(self,destdir,createDir=False):
        """docstring for setDestdir"""
        self._destdir = os.path.abspath(destdir)
        if os.path.exists(destdir):
            self._destdir = destdir
            self.log.debug("Will create files in '%s'" % self._destdir)
        else:
            if(createDir):
                try:
                    os.mkdir(destdir)
                except:
                    raise
            else:
                raise Exception("Directory does not exist %s" % destdir)


    def startRecording(self,episode,autoStop=None):
        """Start the recording of received data.
        Arguments:
        episode: The current episode that is to be recorded. Register this recording with the episode by calling episode.register(IKNRecording-instance)
        Keyword Arguments:
        autoStop: Automatically stop this recording in x seconds
        Returns:
        On success an IKNRecording object is returned.
        """
        self.episode = episode
        self.setDestdir(episode.destinationDirectory + os.path.sep + 'httplive',True)
        self.segmentDir = []

        for outlet in self.outlets:
            outlet.setDestdir(self._destdir + os.path.sep + outlet.name)
            outlet.startRecording()
        self.writeVariantsM3U8()

    def stopRecording(self):
        """Stop the recording process."""
        self.log.debug('Stopping')
        for outlet in self.outlets:
            outlet.stopRecording()


    def writeVariantsM3U8(self):
        fd, m3u8tmpfilename = tempfile.mkstemp(suffix=".static.m3u8")
        fd2, m3u8tmpphpfilename = tempfile.mkstemp(suffix=".m3u8")
        m3u8tmp = os.fdopen(fd, "w+b")
        m3u8tmpphp = os.fdopen(fd2, "w+b")
        os.fchmod(fd,0664)
        os.fchmod(fd2,0664)
        m3u8tmpphp.write("<?php include('../../../userscript.php'); header('Content-type: application/vnd.apple.mpegurl')?>\n")
        m3u8tmp.write("#EXTM3U\n")
        m3u8tmpphp.write("#EXTM3U\n")
        m3u8tmp.write("#EXT-X-VERSION:3\n")
        m3u8tmpphp.write("#EXT-X-VERSION:3\n")
        for quality in self.outlets:
            if quality.getResolution() is not None:
                m3u8tmp.write('#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=%s,CODECS="%s",RESOLUTION=%s\n' % (quality.getMaxBandwidth(),quality.getCodecs(),quality.getResolution()))
                m3u8tmpphp.write('#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=%s,CODECS="%s",RESOLUTION=%s\n' % (quality.getMaxBandwidth(),quality.getCodecs(),quality.getResolution()))
            else:
                m3u8tmp.write('#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=%s,CODECS="%s"\n' % (quality.getMaxBandwidth(),quality.getCodecs()))
                m3u8tmpphp.write('#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=%s,CODECS="%s"\n' % (quality.getMaxBandwidth(),quality.getCodecs()))

            m3u8tmpphp.write("<?php user1('%s/stream.m3u8');?>\n" % quality.name)
            m3u8tmp.write("%s/stream.m3u8\n" % quality.name)

        m3u8tmp.close()
        m3u8tmpphp.close()
        destfile = "%s%s%s.static.m3u8" % (self._destdir,os.path.sep,self.channel.slug)
        destfile2 = "%s%s%s.m3u8" % (self._destdir,os.path.sep,self.channel.slug)
        self.log.debug("Moving %s to %s" % (m3u8tmpfilename,destfile))
        self.log.debug("Moving %s to %s" % (m3u8tmpphpfilename,destfile2))
        shutil.move(m3u8tmpfilename,destfile)
        shutil.move(m3u8tmpphpfilename,destfile2)

        reactor.callLater(30,self.writeVariantsM3U8)

class HTTPLiveVariantStream(KNDistributor):
    """Encode an input mpegts stream to the desired quality and segment the stream to chunks"""
    
    def __init__(self,name,encoderArguments,destdir=None,ffmpegbin=None):
        """
        Args:
        name: Name of this quality (Used in path names)
        encoderArguments: :class:`configobj.ConfigObj` with valid ffmpeg options. This will be passed to a new :class:`FFMpeg` object.
        destdir: The location where files will be saved.
        ffmpegbin: Path to ffmpeg binary.
        """
        super(HTTPLiveVariantStream,self).__init__(name=name)

        self.name = name
        """Name of this variant"""

        self.encoder = None
        """The :class:`FFMpeg` object used for encoding"""

        self.segmenter = None
        """The :class:`HTTPLiveSegmenter` object used for segmenting"""

        # self.destinationDirectory = None
        self.setDestdir(destdir)
        self.destinationDirectory = None
        # Set up the encoder
        if ffmpegbin:
            self.encoder = FFMpeg(ffmpegbin=ffmpegbin,encoderArguments=encoderArguments)
        else:
            self.encoder = FFMpeg(encoderArguments=encoderArguments)

        self.segmenter = HTTPLiveSegmenter(self,name=self.name+"_segmenter",destdir=self.destinationDirectory)

        # Hook everything up
        self.addOutlet(self.encoder)
        self.encoder.addOutlet(self.segmenter)
        self.encoderArguments = encoderArguments


        self.filesizes = deque(10*[100000],10)

    def willStart(self):
        config = self._findObjectInInletChainOfClass(knive.Knive).config
        self.segmenter.segmenterbin = config['paths']['segmenterbin']

        
    def setDestdir(self,destdir,createDir=True):
        """Set the location where files will be saved to destdir.

        Args:
            createDir: (bool) Create the directory if it doesn't exist already. Else throws an exception.
        """
        if destdir is None:
            self.destinationDirectory = destdir
        else:
            try:
                self.segmenter.lastFile = False
            except AttributeError:
                pass
            self.log.debug("Setting destinationDirectory to %s" % destdir)
            destdir = os.path.abspath(destdir)
            if os.path.exists(destdir):
                self.destinationDirectory = destdir
                self.log.debug("Will create files in '%s'" % self.destinationDirectory)
            else:
                if(createDir):
                    try:
                        os.mkdir(destdir)
                        self.setDestdir(destdir)
                    except:
                        raise
                else:
                    raise Exception("Directory does not exist %s" % destdir)

    def startRecording(self):
        self.segmenter.startRecording()

    def stopRecording(self):
        self.log.debug('Stopping')
        self.segmenter.stopRecording()

    def getAverageQuality(self):
        totsize = 0
        for size in self.filesizes:
            totsize = totsize + size
        return int(totsize/10*8)

    def getMaxBandwidth(self):
        rate = self.encoderArguments['maxrate']
        return int(rate[:-1]) * 1024

    def updateBandwidthAverage(self,size):
        self.filesizes.appendleft(size)

    def getResolution(self):
        res = None
        try:
            res = self.encoderArguments['s']
        except KeyError:
            pass
        return res

    def getCodecs(self):
        if(isinstance(self.encoderArguments['codecstring'],list)):
            return ",".join(self.encoderArguments['codecstring'])
        else:
            return self.encoderArguments['codecstring']


class HTTPLiveSegmenter(KNOutlet):
    """Cuts mpeg-ts streams in chunks and creates index files."""
    def __init__(self,variant, name="Unknown segmenter",segmenterbin=None,destdir=None,tempdir=None):
        """
        Kwargs:
            name: Name of this segmenter.
            segmenterbin: Path to the segmenter binary
            destdir: The location where ready files will be moved to.
            tempdir: Location where tempfiles will be written. If None, let python decide.
        """

        super(HTTPLiveSegmenter, self).__init__(name=name)
        self.variant = variant
        self.name = name
        """Name of this segmenter"""

        self.lastFile = False

        self.segmenterbin = None
        if segmenterbin:
            self._setSegmenterbin(segmenterbin)
        """The segmenter binary to be used (path)"""

        self.m3u8 = None
        """The :class:`HTTPLiveStreamM3U8` object associated with this segmenter."""

        self.httpStream = None
        """The :class:`HTTPLiveStream` this segmenter belongs to. This is determined automatially."""

        if tempdir is None:
            self._tempdir = tempfile.gettempdir()
        else:
            self._tempdir = tempdir

        self._protocol = SegmenterProtocol()
        self._protocol.factory = self
        
    def _start(self):
        """All preparations done. Start the process"""
        self.httpStream = self._findObjectInInletChainOfClass(HTTPLiveStream)
        variant = self._findObjectInInletChainOfClass(HTTPLiveVariantStream)
        channel = self._findObjectInInletChainOfClass(Channel)
        if not channel:
            raise(Exception('Cant find channel'))
        if self.segmenterbin is None:
            self._setSegmenterbin(channel.config['paths']['segmenterbin'])

        # Fileprefix
        valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
        filePrefix = "%s-%s-" % (channel.slug,variant.name)
        filePrefix = ''.join(c for c in filePrefix if c in valid_chars)
        self.log.debug("FilePrefix: '%s'" % filePrefix)

        self.m3u8 = HTTPLiveStreamM3U8(self.variant)
        
        args = ["live_segmenter","10",self._tempdir,filePrefix,filePrefix]
        self.cmdline = "%s %s" % (self.segmenterbin, " ".join(args))
        self.log.debug("Spawning Process: %s" % self.cmdline)
        reactor.spawnProcess(self._protocol,self.segmenterbin,args)

    def _setSegmenterbin(self,segmenterbin):
        if os.path.exists(segmenterbin):
            self.segmenterbin = segmenterbin
        else:
            raise OSError(2, 'No such file or directory', segmenterbin)

    def startRecording(self):
        urlPrefix = "%s/%s/%s/httplive/%s" % (self.httpStream.segmentServer,self.httpStream.channel.slug,self.httpStream.episode.name,self.variant.name)
        self.m3u8.urlPrefix = urlPrefix

    def dataReceived(self,data):
        """Data received from our inlet. Pipe this data to the ffmpeg process"""
        if not self.running:
            raise(Exception("Process not running"))
        else:
            self._protocol.writeData(data)
    
    def segmentReady(self,startindex,lastindex,end,encodingprofile,duration):
        """A segment is ready for transfer"""
        #umts-00000001.ts
        duration = float(duration)
        liveStreamObj = self.variant._findObjectInInletChainOfClass(HTTPLiveStream)

        try:
            if liveStreamObj.episode.starttime is not None:
                isRecording = True
        except:
            pass
        
        self.httpStream.setLastIndex(int(lastindex))
        filename = "%s-%08d.ts" % (encodingprofile,int(lastindex))
        sourcefile = os.path.abspath("%s%s%s" % (self._tempdir,os.path.sep,filename))
        self.variant.updateBandwidthAverage(os.stat(sourcefile).st_size/duration)
        
        if self.variant.destinationDirectory is None:
            # Delete files
            os.unlink(sourcefile)
        else:
            destfile = os.path.abspath("%s%s%s" % (self.variant.destinationDirectory,os.path.sep,self.m3u8.addSegment(duration)))
            self.log.debug("Moving file %s to %s" % (sourcefile,destfile))
            
            #FIXME: This is propably a blocking call!
            shutil.move(sourcefile,destfile)
            self.m3u8.writeIndexFile(isRecording=isRecording,isLast=self.lastFile)
            if self.lastFile:
                self.variant.setDestdir(None)
                self.m3u8.emptySegmentList()

    def stopRecording(self):
        self.log.debug('Stopping')
        self.lastFile = True


class SegmenterProtocol(KNProcessProtocol):
    factory = None
    REtransfer = re.compile('segmenter: *(?P<startindex>\d+), *(?P<lastindex>\d+), *(?P<end>\d+), *(?P<encodingprofile>[^,]+), *(?P<duration>\d+\.\d+)')
    
    def errReceived(self, data):
        lines = str(data).splitlines()
        for line in lines:
        #segmenter: 1, 1, 0, 600
        # <firstsegment>, <lastsegment>, <end>, <encodingprofile>
        # Example: 'segmenter: 1, 46, 0, bus-wifi-, 10.00'
            if len(line)>1:
                segmentcommand = self.REtransfer.match(line)
                if(segmentcommand):
                    self.log.debug("Startindex: %s Lastindex: %s End: %s Encodingprofile: %s Duration: %s" % (segmentcommand.group(1),segmentcommand.group(2),segmentcommand.group(3),segmentcommand.group(4),segmentcommand.group(5)))
                    self.factory.segmentReady(segmentcommand.group(1),segmentcommand.group(2),segmentcommand.group(3),segmentcommand.group(4),segmentcommand.group(5))
                else:
                    self.log.warn("Unknown line from segmenter:'%s'" % line)


class HTTPLiveStreamM3U8(object):
    """Representation of a HTTPLive Stream indexfile"""
    def __init__(self, httplivestreamvariant, startIndex=1, maxSegments=10, urlPrefix=None, filename="stream.m3u8", segmentLength=10, segmentPrefix="s", allowCache=False,version=3,extKey=None,datetime=datetime.time()):
        super(HTTPLiveStreamM3U8, self).__init__()
        self.httplivestreamvariant = httplivestreamvariant
        self.filename = filename
        self.segmentLength = segmentLength
        self.segmentPrefix = segmentPrefix
        self.allowCache = allowCache
        self.version = version
        self.extKey = extKey
        self.datetime = datetime
        self.maxSegments = maxSegments
        self.startIndex = startIndex
        self.urlPrefix = urlPrefix
        
        self.lastIndex = self.startIndex
        self.segmenttitle = None

        self.logger = logging.getLogger('[%s]' % (self.__class__.__name__))

        self.segments = []

    def emptySegmentList(self):
        self.segments = []
        
    def setParent(self,parent):
        """set self.parent and also inherit the lastIndex"""
        super(HTTPLiveStreamM3U8,self).setParent(parent)
        if self.lastIndex is None:
            # print parent
            self.lastIndex = self.httplivestreamvariant._findObjectInInletChainOfClass(HTTPLiveStream).lastIndex
        self.segmenttitle = self.httplivestreamvariant._findObjectInInletChainOfClass(Channel).name
        
    def addSegment(self,segmentLength=10):
        """Add a segment to the stream and return the filename of the segment"""
        httpLiveStreamObj = self.httplivestreamvariant._findObjectInInletChainOfClass(HTTPLiveStream)
        try:
            segmentSeed = httpLiveStreamObj.segmentIndex[self.lastIndex]
        except KeyError:
            segmentSeed = random.randint(1,10000)
            httpLiveStreamObj.segmentIndex[self.lastIndex] = segmentSeed
        segmentName = "%s-%s-%d" % (self.segmentPrefix, segmentSeed , self.lastIndex)
        segmentName = "%s.ts" % segmentName
        # segmentName = "%s.ts" % sha.sha(segmentName).hexdigest()

        segment = HTTPLiveStreamSegment(self.lastIndex,segmentName,self.segmentLength,time.time())
        self.logger.debug("Segment name: %s Segment Length: %.1f Segment Time: %s " % (segment,float(segment.length),segment.iso8601()))
        self.segments.append(segment)
        self.lastIndex += 1
        return(segment)
        
    def writeIndexFile(self,isRecording=False,isLast=False):
        """Write a current representation of the object to a file in self.dstPath + self.filename"""
        
        fd, m3u8tmpfilename = tempfile.mkstemp(suffix=".m3u8")
        m3u8tmp = os.fdopen(fd, "w+b")
        os.fchmod(fd,0664)
        m3u8tmp.write("#EXTM3U\n")
        m3u8tmp.write("#EXT-X-VERSION:%s\n" % (self.version))
        m3u8tmp.write("#EXT-X-TARGETDURATION:%d\n" % int(self.segmentLength))
        if self.allowCache:
            m3u8tmp.write("#EXT-X-ALLOW-CACHE:YES\n")
        else:
            m3u8tmp.write("#EXT-X-ALLOW-CACHE:NO\n")
        
        # EXT-X-MEDIASEQUENCE
        # For sliding-window (live) streams this is the lastIndex - 3.
        # For timeshift it is the firstIndex since start
        # For non-sliding-window it's the firstIndex

        # Disabled.. let's assume users can navigate to the beginning of a file if they want to
        # mediasequence = 1
        # if self.parent.findParentOfType(HTTPLiveStream).slidingWindow:
        #     self.logger.debug("Sliding window stream. Current last index: %s" % self.lastIndex)
        #     mediasequence = self.lastIndex - 3
        # else:
        #     mediasequence = self.startIndex
        mediasequence = 1
        # mediasequence = self.lastIndex - 3
        
        if(mediasequence < 1):
            mediasequence = 1
        # m3u8tmp.write("#EXT-X-MEDIA-SEQUENCE:%d\n" % int(mediasequence))

        def _writeLine(segment):
            # m3u8tmp.write("#EXT-X-PROGRAM-DATE-TIME:%s\n" % (segment.iso8601()))
            m3u8tmp.write("#EXTINF:%0.2f,%s\n" % (float(segment.length), self.segmenttitle))
            if self.urlPrefix is not None:
                m3u8tmp.write("%s/" % self.urlPrefix)
            m3u8tmp.write("%s\n" % (segment.filename))
        
        if isRecording:
            if isLast:
               for segment in self.segments:
                _writeLine(segment)
            else: 
                for segment in self.segments[:-2]:
                    _writeLine(segment)
        else:
            for segment in self.segments[(self.maxSegments*-1):-2]:
                _writeLine(segment)

        if isLast:
            m3u8tmp.write('#EXT-X-ENDLIST\n')
        
        
        m3u8tmp.close()
        destfile = "%s%s%s" % (self.httplivestreamvariant.destinationDirectory,os.path.sep,self.filename)
        self.logger.debug("Moving %s to %s" % (m3u8tmpfilename,destfile))
        shutil.move(m3u8tmpfilename,destfile)
        ##EXTM3U
        #EXT-X-TARGETDURATION:7
        #EXT-X-MEDIA-SEQUENCE:0
        #EXTINF:7,    
        #fileSequence0.ts
        


class HTTPLiveStreamSegment(object):
    """An individual segment in a HTTPLiveStreamVariant"""
    def __init__(self, index, filename, length, timestamp):
        super(HTTPLiveStreamSegment, self).__init__()
        self.index = index
        self.filename = filename
        self.length = length
        self.timestamp = timestamp
        
    def __str__(self):
        return str(self.filename)
        
    def iso8601(self):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime(self.timestamp))
        
      
