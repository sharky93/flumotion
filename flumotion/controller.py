# -*- Mode: Python -*-
# Flumotion - a video streaming server
# Copyright (C) 2004 Fluendo
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import atexit
import os
import socket
import time
import sys

from twisted.spread import pb
from twisted.internet import reactor

from transcoder import TranscoderFactory
from acquisition import AcquisitionFactory

class AcquisitionManager:
    def __init__(self, control):
        self.control = control
        self.objs = {}
        
    def create(self, port=8800, interface='', pipeline=''):
        factory = pb.PBServerFactory(AcquisitionFactory(pipeline))
        f = reactor.listenTCP(port, factory, 5, interface)

        if interface == '':
            interface = socket.gethostname()
        return interface, port

    def onConnect(self, object, control):
        d = object.callRemote('setController', control)
        def getRetval(object_id):
            self.objs[object_id] = object
        d.addCallback(getRetval)
        return object
        
    def connect(self, hostname, port):
        factory = pb.PBClientFactory()
        reactor.connectTCP(hostname, port, factory)

        object = factory.getRootObject()
        object.addCallback(self.onConnect, self.control)
        return object
    
class TranscoderManager:
    def __init__(self, control):
        self.control = control

    def create(self, port=8800, interface=''):
        factory = pb.PBServerFactory(TranscoderFactory())
        f = reactor.listenTCP(port, factory, 5, interface)
        if interface == '':
            interface = socket.gethostname()
            
        return interface, port

    def connect(self, hostname, port):
        factory = pb.PBClientFactory()
        reactor.connectTCP(hostname, port, factory)
        
        object = factory.getRootObject()
        def onConnect(obj, control):
            d = obj.callRemote('setController', control)
            return obj
        object.addCallback(onConnect, self.control)

        return object
    
class ControllerFactory(pb.Referenceable):
    def __init__(self):
        self.objs = {}
        self.acq_mgr = AcquisitionManager(self)
        self.trans_mgr = TranscoderManager(self)
        
    def createAcquisition(self, port=8800, interface='', pipeline=''):
        return self.acq_mgr.create(port, interface, pipeline)
        
    def createTranscoder(self, port=8800, interface=''):
        return self.trans_mgr.create(port, interface)

    def connectAcquisition(self, hostname, port):
        return self.acq_mgr.connect(hostname, port)

    def connectTranscoder(self, hostname, port):
        return self.trans_mgr.connect(hostname, port)

    def link(self, first, second):
        print 'Going to link', first, 'with', second

        def onConnect(obj, other):
            if hasattr(other, 'result'):
                self.objs[obj.processUniqueID()] = other.result
                self.objs[other.result.processUniqueID()] = obj
            obj.callRemote('startFileSink', '/tmp/foo')
            return obj

        first.addCallback(onConnect, second)
        
        def onConnect2(obj, other):
            if hasattr(other, 'result'):
                self.objs[obj.processUniqueID()] = other.result
                self.objs[other.result.processUniqueID()] = obj
            #obj.callRemote('startFileSrc', '/tmp/foo')
            obj.callRemote('startFileSrc', '/tmp/foo')
            return obj

        second.addCallback(onConnect2, first)

    def remote_acqStarted(self, acq):
        print 'Controller.remote_acqStarted', acq
        
    def remote_acqFinished(self, acq):
        print 'Controller.remote_acquisitionFinished', acq

    def remote_acqNotifyCaps(self, acq_id, caps):
        print 'Controller.remote_acqNotifyCaps', caps

        #print 'FIXME: Retrieve transcoder for acq'
        #print acq_id
        acq = self.acq_mgr.objs[acq_id]
        transcoder = self.objs[acq.processUniqueID()]
        transcoder.callRemote('setCaps', caps)
        acq.callRemote('assignRealSink')

        # XXX: Un-tie
        #transcoder = self.trans_mgr.transcoder
        #transcoder.addCallback(lambda obj: obj.callRemote('setCaps', caps))
            
    def remote_transStarted(self, trans):
        print 'Controller.remote_transStarted', trans
        
if __name__ == '__main__':
    controller = ControllerFactory()

    filename = '/tmp/foo'
    if os.path.exists(filename):
        os.unlink(filename)
        os.mkfifo(filename, 0600)

    #pipeline = 'filesrc location="/home/jdahlin/Movies/alien.mpg" ! mpegdemux ! mpeg2dec'
    pipeline = 'videotestsrc' # ! identity'
    #hostname, port = controller.createAcquisition(8802, pipeline=pipeline)
    hostname = 'localhost'
    port = 8802
    acq = controller.connectAcquisition(hostname, port)
    
    #hostname, port = controller.createTranscoder(8803)
    hostname = 'localhost'
    port = 8803
    trans = controller.connectTranscoder(hostname, port)

    controller.link(acq, trans)
    
    reactor.run()
