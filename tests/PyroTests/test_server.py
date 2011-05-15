"""
Tests for a running Pyro server, without timeouts.

Pyro - Python Remote Objects.  Copyright by Irmen de Jong.
irmen@razorvine.net - http://www.razorvine.net/python/Pyro
"""

from __future__ import with_statement
import unittest
import Pyro4.core
import Pyro4.errors
import Pyro4.util
import time, os, sys
from Pyro4 import threadutil

if sys.version_info>=(3,0):
    unicode=str
    unichr=chr

class MyThing(object):
    def __init__(self):
        self.dictionary={"number":42}
    def getDict(self):
        return self.dictionary
    def multiply(self,x,y):
        return x*y
    def divide(self,x,y):
        return x//y
    def ping(self):
        pass
    def delay(self, delay):
        time.sleep(delay)
        return "slept %d seconds" % delay
    def delayAndId(self, delay, id):
        time.sleep(delay)
        return "slept for "+str(id)
    def testargs(self,x,*args,**kwargs):
        return x,args,kwargs

class DaemonLoopThread(threadutil.Thread):
    def __init__(self, pyrodaemon):
        super(DaemonLoopThread,self).__init__()
        self.setDaemon(True)
        self.pyrodaemon=pyrodaemon
        self.running=threadutil.Event()
        self.running.clear()
    def run(self):
        self.running.set()
        try:
            self.pyrodaemon.requestLoop()
        except:
            print("Swallow exception from terminated daemon")
        
class ServerTestsThreadNoTimeout(unittest.TestCase):
    SERVERTYPE="thread"
    COMMTIMEOUT=None
    def setUp(self):
        Pyro4.config.POLLTIMEOUT=0.1
        Pyro4.config.SERVERTYPE=self.SERVERTYPE
        Pyro4.config.COMMTIMEOUT=self.COMMTIMEOUT
        Pyro4.config.THREADPOOL_MINTHREADS=2
        Pyro4.config.THREADPOOL_MAXTHREADS=20
        Pyro4.config.HMAC_KEY="testsuite"
        self.daemon=Pyro4.core.Daemon(port=0)
        obj=MyThing()
        uri=self.daemon.register(obj, "something")
        self.objectUri=uri
        self.daemonthread=DaemonLoopThread(self.daemon)
        self.daemonthread.start()
        self.daemonthread.running.wait()
    def tearDown(self):
        time.sleep(0.05)
        self.daemon.shutdown()
        self.daemonthread.join()
        Pyro4.config.SERVERTYPE="thread"
        Pyro4.config.COMMTIMEOUT=None
        Pyro4.config.HMAC_KEY=None

    def testNoDottedNames(self):
        Pyro4.config.DOTTEDNAMES=False
        with Pyro4.core.Proxy(self.objectUri) as p:
            self.assertEqual(55,p.multiply(5,11))
            x=p.getDict()
            self.assertEqual({"number":42}, x)
            try:
                p.dictionary.update({"more":666})     # should fail with DOTTEDNAMES=False (the default)
                self.fail("expected AttributeError")
            except AttributeError:
                pass
            x=p.getDict()
            self.assertEqual({"number":42}, x)
            # also test some argument type things
            self.assertEqual((1,(),{}), p.testargs(1))
            self.assertEqual((1,(2,3),{'a':4}), p.testargs(1,2,3,a=4))
            self.assertEqual((1,(),{'a':2}), p.testargs(1, **{'a':2}))
            if sys.version_info>=(2,6,5):
                # python 2.6.5 and later support unicode keyword args
                result=p.testargs(1, **{unichr(0x20ac):2})
                key=list(result[2].keys())[0]
                self.assertTrue(key==unichr(0x20ac))


    def testDottedNames(self):
        try:
            Pyro4.config.DOTTEDNAMES=True
            with Pyro4.core.Proxy(self.objectUri) as p:
                self.assertEqual(55,p.multiply(5,11))
                x=p.getDict()
                self.assertEqual({"number":42}, x)
                p.dictionary.update({"more":666})    # updating it remotely should work with DOTTEDNAMES=True
                x=p.getDict()
                self.assertEqual({"number":42, "more":666}, x)  # eek, it got updated!
        finally:
            Pyro4.config.DOTTEDNAMES=False

    def testConnectionStuff(self):
        p1=Pyro4.core.Proxy(self.objectUri)
        p2=Pyro4.core.Proxy(self.objectUri)
        self.assertTrue(p1._pyroConnection is None)
        self.assertTrue(p2._pyroConnection is None)
        p1.ping()
        p2.ping()
        _=p1.multiply(11,5)
        _=p2.multiply(11,5)
        self.assertTrue(p1._pyroConnection is not None)
        self.assertTrue(p2._pyroConnection is not None)
        p1._pyroRelease()
        p1._pyroRelease()
        p2._pyroRelease()
        p2._pyroRelease()
        self.assertTrue(p1._pyroConnection is None)
        self.assertTrue(p2._pyroConnection is None)
        p1._pyroBind()
        _=p1.multiply(11,5)
        _=p2.multiply(11,5)
        self.assertTrue(p1._pyroConnection is not None)
        self.assertTrue(p2._pyroConnection is not None)
        self.assertEqual("PYRO",p1._pyroUri.protocol)
        self.assertEqual("PYRO",p2._pyroUri.protocol)
        p1._pyroRelease()
        p2._pyroRelease()

    def testReconnectAndCompression(self):
        # try reconnects
        with Pyro4.core.Proxy(self.objectUri) as p:
            self.assertTrue(p._pyroConnection is None)
            p._pyroReconnect(tries=100)
            self.assertTrue(p._pyroConnection is not None)
        self.assertTrue(p._pyroConnection is None)
        # test compression:
        try:
            with Pyro4.core.Proxy(self.objectUri) as p:
                Pyro4.config.COMPRESSION=True
                self.assertEqual(55, p.multiply(5,11))
                self.assertEqual("*"*1000, p.multiply("*"*500,2))
        finally:
            Pyro4.config.COMPRESSION=False
    
    def testOneway(self):
        with Pyro4.core.Proxy(self.objectUri) as p:
            self.assertEqual(55, p.multiply(5,11))
            p._pyroOneway.add("multiply")
            self.assertEqual(None, p.multiply(5,11))
            self.assertEqual(None, p.multiply(5,11))
            self.assertEqual(None, p.multiply(5,11))
            p._pyroOneway.remove("multiply")
            self.assertEqual(55, p.multiply(5,11))
            self.assertEqual(55, p.multiply(5,11))
            self.assertEqual(55, p.multiply(5,11))
            # check nonexisting method behavoir
            self.assertRaises(AttributeError, p.nonexisting)
            p._pyroOneway.add("nonexisting")
            # now it shouldn't fail because of oneway semantics
            p.nonexisting()
        # also test on class:
        class ProxyWithOneway(Pyro4.core.Proxy):
            def __init__(self, arg):
                super(ProxyWithOneway,self).__init__(arg)
                self._pyroOneway=["multiply"]   # set is faster but don't care for this test
        with ProxyWithOneway(self.objectUri) as p:
            self.assertEqual(None, p.multiply(5,11))
            p._pyroOneway=[]   # empty set is better but don't care in this test
            self.assertEqual(55, p.multiply(5,11))
            
    def testOnewayDelayed(self):
        try:
            with Pyro4.core.Proxy(self.objectUri) as p:
                p.ping()
                Pyro4.config.ONEWAY_THREADED=True   # the default
                p._pyroOneway.add("delay")
                now=time.time()
                p.delay(1)  # oneway so we should continue right away
                self.assertTrue(time.time()-now < 0.2, "delay should be running as oneway")
                now=time.time()
                self.assertEqual(55,p.multiply(5,11), "expected a normal result from a non-oneway call")
                self.assertTrue(time.time()-now < 0.2, "delay should be running in its own thread")
                # make oneway calls run in the server thread
                # we can change the config here and the server will pick it up on the fly
                Pyro4.config.ONEWAY_THREADED=False   
                now=time.time()
                p.delay(1)  # oneway so we should continue right away
                self.assertTrue(time.time()-now < 0.2, "delay should be running as oneway")
                now=time.time()
                self.assertEqual(55,p.multiply(5,11), "expected a normal result from a non-oneway call")
                self.assertFalse(time.time()-now < 0.2, "delay should be running in the server thread")
        finally:
            Pyro4.config.ONEWAY_THREADED=True   # back to normal

    def testSerializeConnected(self):
        # online serialization tests
        ser=Pyro4.util.Serializer()
        proxy=Pyro4.core.Proxy(self.objectUri)
        proxy._pyroBind()
        self.assertFalse(proxy._pyroConnection is None)
        p,_=ser.serialize(proxy)
        proxy2=ser.deserialize(p)
        self.assertTrue(proxy2._pyroConnection is None)
        self.assertFalse(proxy._pyroConnection is None)
        self.assertEqual(proxy2._pyroUri, proxy._pyroUri)
        self.assertEqual(proxy2._pyroSerializer, proxy._pyroSerializer)
        proxy2._pyroBind()
        self.assertFalse(proxy2._pyroConnection is None)
        self.assertFalse(proxy2._pyroConnection is proxy._pyroConnection)
        proxy._pyroRelease()
        proxy2._pyroRelease()
        self.assertTrue(proxy._pyroConnection is None)
        self.assertTrue(proxy2._pyroConnection is None)
        proxy.ping()
        proxy2.ping()
        # try copying a connected proxy
        import copy
        proxy3=copy.copy(proxy)
        self.assertTrue(proxy3._pyroConnection is None)
        self.assertFalse(proxy._pyroConnection is None)
        self.assertEqual(proxy3._pyroUri, proxy._pyroUri)
        self.assertFalse(proxy3._pyroUri is proxy._pyroUri)
        self.assertEqual(proxy3._pyroSerializer, proxy._pyroSerializer)        
        proxy._pyroRelease()
        proxy2._pyroRelease()
        proxy3._pyroRelease()

    def testException(self):
        with Pyro4.core.Proxy(self.objectUri) as p:
            try:
                p.divide(1,0)
            except:
                et,ev,tb=sys.exc_info()
                self.assertEqual(ZeroDivisionError, et)
                pyrotb="".join(Pyro4.util.getPyroTraceback(et,ev,tb))
                self.assertTrue("Remote traceback" in pyrotb)    # fails on ironpython...
                self.assertTrue("ZeroDivisionError" in pyrotb)
                del tb

    def testTimeoutCall(self):
        Pyro4.config.COMMTIMEOUT=None
        with Pyro4.core.Proxy(self.objectUri) as p:
            p.ping()
            start=time.time()
            p.delay(0.5)
            duration=time.time()-start
            self.assertAlmostEqual(0.5, duration, places=1)
            p._pyroTimeout=0.1
            start=time.time()
            self.assertRaises(Pyro4.errors.TimeoutError, p.delay, 1)
            duration=time.time()-start
            if sys.platform!="cli":
                self.assertAlmostEqual(0.1, duration, places=1)
            else:
                # ironpython's time is wonky
                self.assertTrue(0.0<duration<0.7)

    def testTimeoutConnect(self):
        # set up a unresponsive daemon
        with Pyro4.core.Daemon(port=0) as d:
            time.sleep(0.5)
            obj=MyThing()
            uri=d.register(obj)
            # we're not going to start the daemon's event loop
            p=Pyro4.core.Proxy(uri)
            p._pyroTimeout=0.2
            start=time.time()
            self.assertRaises(Pyro4.errors.TimeoutError, p.ping)
            duration=time.time()-start
            self.assertTrue(duration<2.0)
            
    def testProxySharing(self):
        class SharedProxyThread(threadutil.Thread):
            def __init__(self, proxy):
                super(SharedProxyThread,self).__init__()
                self.proxy=proxy
                self.terminate=False
                self.error=True
                self.setDaemon(True)
            def run(self):
                try:
                    while not self.terminate:
                        reply=self.proxy.multiply(5,11)
                        assert reply==55
                        time.sleep(0.001)
                    self.error=False
                except:
                    print("Something went wrong in the thread (SharedProxyThread):")
                    print("".join(Pyro4.util.getPyroTraceback()))
        with Pyro4.core.Proxy(self.objectUri) as p:
            threads=[]
            for i in range(5):
                t=SharedProxyThread(p)
                threads.append(t)
                t.start()
            time.sleep(1)
            for t in threads:
                t.terminate=True
                t.join()
            for t in threads:
                self.assertFalse(t.error, "all threads should report no errors") 

    def testServerConnections(self):
        # check if the server allows to grow the number of connections
        proxies=[Pyro4.core.Proxy(self.objectUri) for _ in range(10)]
        try:
            for p in proxies:
                p._pyroTimeout=0.5
                p._pyroBind()
            for p in proxies:
                p.ping()
        finally:
            for p in proxies:
                p._pyroRelease()

    def testServerParallelism(self):
        class ClientThread(threadutil.Thread):
            def __init__(self, uri, name):
                super(ClientThread,self).__init__()
                self.setDaemon(True)
                self.proxy=Pyro4.core.Proxy(uri)
                self.name=name
                self.error=True
                self.proxy._pyroTimeout=5.0
                self.proxy._pyroBind()
            def run(self):
                try:
                    reply=self.proxy.delayAndId(0.5, self.name)
                    assert reply=="slept for "+self.name
                    self.error=False
                finally:
                    self.proxy._pyroRelease()
        threads=[]
        start=time.time()
        try:
            for i in range(6):
                t=ClientThread(self.objectUri,"t%d" % i)
                threads.append(t)
        except:
            # some exception (probably timeout) while creating clients
            # try to clean up some connections first
            for t in threads:
                t.proxy._pyroRelease()
            raise  # re-raise the exception
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            self.assertFalse(t.error, "all threads should report no errors")
        del threads
        duration=time.time()-start
        if Pyro4.config.SERVERTYPE=="select":
            # select based server doesn't execute calls in parallel,
            # so 6 threads times 0.5 seconds =~ 3 seconds
            self.assertTrue(2.5<duration<3.5)
        else:
            # thread based server does execute calls in parallel,
            # so 6 threads taking 0.5 seconds =~ 0.5 seconds passed
            self.assertTrue(0.3<duration<0.7)

if os.name!="java":
    class ServerTestsSelectNoTimeout(ServerTestsThreadNoTimeout):
        SERVERTYPE="select"
        COMMTIMEOUT=None
        def testProxySharing(self):
            pass
        def testException(self):
            pass

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()