#!/usr/bin/env python 

__author__ = "John Hover, Jose Caballero"
__copyright__ = "2017 John Hover"
__credits__ = []
__license__ = "GPL"
__version__ = "1.0.0"
__maintainer__ = "John Hover"
__email__ = "jhover@bnl.gov"
__status__ = "Production"


import logging
import logging.handlers
import os
import platform
import pwd
import random
import json
import string
import socket
import sys
import threading
import time
import traceback

from optparse import OptionParser
from ConfigParser import ConfigParser

# Since script is in package "vc3" we can know what to add to path for 
# running directly during development
(libpath,tail) = os.path.split(sys.path[0])
sys.path.append(libpath)

import pluginmanager as pm

from vc3infoservice.infoclient import InfoClient
from vc3client.client import VC3ClientAPI
from vc3master.task import VC3TaskSet
from credible.core import SSCA, SSHKeyManager

class VC3Master(object):
    
    def __init__(self, config):
        self.log = logging.getLogger()
        self.log.debug('VC3Master class init...')

        self.config = config

        self.certfile  = os.path.expanduser(config.get('netcomm','certfile'))
        self.keyfile   = os.path.expanduser(config.get('netcomm', 'keyfile'))
        self.chainfile = os.path.expanduser(config.get('netcomm','chainfile'))

        self.client    = VC3ClientAPI(config)
        
        #self.dynpluginname = config.get('dynamic','plugin')
        #self.dynpluginsection = "plugin-%s" % self.dynpluginname.lower() 
        
        #self.log.debug("Creating dynamic plugin...")
        #self.dynamic = pm.getplugin(parent=self, 
        #                            paths=['vc3', 'plugins', 'dynamic'], 
        #                            name=self.dynpluginname, 
        #                            config=self.config, 
        #                            section=self.dynpluginsection)

        self.log.debug("certfile=%s" % self.certfile)
        self.log.debug("keyfile=%s" % self.keyfile)
        self.log.debug("chainfile=%s" % self.chainfile)

        self.credconfig = ConfigParser()
        self.credconfig.read(os.path.expanduser(self.config.get('credible','credconf')))
        
        self.ssca = SSCA( self.credconfig ) 
        self.ssh = SSHKeyManager(self.credconfig) 

        self.infoclient = InfoClient(config)
       
        self.taskconfig = ConfigParser()
        self.taskconfig.read(os.path.expanduser(self.config.get('master','taskconf')))

        self.tasksets = []
        for tset in self.taskconfig.sections():
            self.log.debug("Handling taskset %s" % tset)
            ts = VC3TaskSet(self, self.taskconfig, tset)
            self.tasksets.append(ts)
        self.log.debug('Tasksets loaded.')        
            
        self.log.debug('VC3Master class done.')
   
        
    def run(self):
        self.log.debug('Master running...')
        for ts in self.tasksets:
            self.log.debug("Starting taskset thread %s" % ts.section)
            ts.start()
        self.log.debug("All TaskSet threads started...")
        
      
    def shutdown(self):
        self.log.debug("Got shutdown command...")
        for ts in self.tasksets:
            ts.join()
        self.log.debug("Done.")



class VC3MasterCLI(object):
    """class to handle the command line invocation of service. 
       parse the input options,
       setup everything, and run VC3Master class
    """
    def __init__(self):
        self.options = None 
        self.args = None
        self.log = None
        self.config = None

        self.__presetups()
        self.__parseopts()
        self.__setuplogging()
        self.__platforminfo()
        self.__checkroot()
        self.__createconfig()

    def __presetups(self):
        '''
        we put here some preliminary steps that 
        for one reason or another 
        must be done before anything else
        '''

    
    def __parseopts(self):
        parser = OptionParser(usage='''%prog [OPTIONS]
vc3-master is a information store for VC3

This program is licensed under the GPL, as set out in LICENSE file.

Author(s):
John Hover <jhover@bnl.gov>
''', version="%prog $Id: master.py 3-3-17 23:58:06Z jhover $" )

        parser.add_option("-d", "--debug", 
                          dest="logLevel", 
                          default=logging.WARNING,
                          action="store_const", 
                          const=logging.DEBUG, 
                          help="Set logging level to DEBUG [default WARNING]")
        parser.add_option("-v", "--info", 
                          dest="logLevel", 
                          default=logging.WARNING,
                          action="store_const", 
                          const=logging.INFO, 
                          help="Set logging level to INFO [default WARNING]")
        parser.add_option("--console", 
                          dest="console", 
                          default=False,
                          action="store_true", 
                          help="Forces debug and info messages to be sent to the console")
        parser.add_option("--quiet", dest="logLevel", 
                          default=logging.WARNING,
                          action="store_const", 
                          const=logging.WARNING, 
                          help="Set logging level to WARNING [default]")
        parser.add_option("--maxlogsize", dest="maxlogsize",
                          default=4096,
                          action="store",
                          type="int",
                          help="Max log size, in MB.")
        parser.add_option("--logrotations", dest="logrotations",
                          default=2,
                          action="store",
                          type="int",
                          help="Number of log backups to keep.")

        default_conf = ','.join(['/etc/vc3/vc3-master.conf', os.path.expanduser('~/.local/etc/vc3-master.conf'), os.path.expanduser('~/.local/etc/vc3-master-local.conf')])

        parser.add_option("--conf", dest="confFiles", 
                          default=default_conf,
                          action="store", 
                          metavar="FILE1[,FILE2,FILE3]", 
                          help="Load configuration from FILEs (comma separated list)")

        parser.add_option("--log", dest="logfile", 
                          default="stdout", 
                          metavar="LOGFILE", 
                          action="store", 
                          help="Send logging output to LOGFILE or SYSLOG or stdout [default <syslog>]")
        parser.add_option("--runas", dest="runAs", 
                          #
                          # By default
                          #
                          default=pwd.getpwuid(os.getuid())[0],
                          action="store", 
                          metavar="USERNAME", 
                          help="If run as root, drop privileges to USER")
        parser.add_option("--builder", dest="builder_path", 
                          #
                          # By default
                          #
                          default='vc3-builder',  # by default, hope the builder is in the PATH
                          action="store", 
                          help="service bootstrapper")
        (self.options, self.args) = parser.parse_args()

        self.options.confFiles = self.options.confFiles.split(',')

    def __setuplogging(self):
        """ 
        Setup logging 
        """
        self.log = logging.getLogger()
        if self.options.logfile == "stdout":
            logStream = logging.StreamHandler()
        else:
            lf = os.path.expanduser(self.options.logfile)
            logdir = os.path.dirname(lf)
            if not os.path.exists(logdir):
                os.makedirs(logdir)
            runuid = pwd.getpwnam(self.options.runAs).pw_uid
            rungid = pwd.getpwnam(self.options.runAs).pw_gid                  
            os.chown(logdir, runuid, rungid)
            #logStream = logging.FileHandler(filename=lf)
            logStream = logging.handlers.RotatingFileHandler(filename=lf, maxBytes=1024 * 1024 * self.options.maxlogsize, backupCount=self.options.logrotations)

        # Check python version 
        major, minor, release, st, num = sys.version_info
        if major == 2 and minor == 4:
            FORMAT='%(asctime)s (UTC) [ %(levelname)s ] %(name)s %(filename)s:%(lineno)d : %(message)s'
        else:
            FORMAT='%(asctime)s (UTC) [ %(levelname)s ] %(name)s %(filename)s:%(lineno)d %(funcName)s(): %(message)s'
        formatter = logging.Formatter(FORMAT)
        formatter.converter = time.gmtime  # to convert timestamps to UTC
        logStream.setFormatter(formatter)
        self.log.addHandler(logStream)

        # adding a new Handler for the console, 
        # to be used only for DEBUG and INFO modes. 
        if self.options.logLevel in [logging.DEBUG, logging.INFO]:
            if self.options.console:
                console = logging.StreamHandler(sys.stdout)
                console.setFormatter(formatter)
                console.setLevel(self.options.logLevel)
                self.log.addHandler(console)
        self.log.setLevel(self.options.logLevel)
        self.log.info('Logging initialized at level %s.' % self.options.logLevel)


    def _printenv(self):

        envmsg = ''        
        for k in sorted(os.environ.keys()):
            envmsg += '\n%s=%s' %(k, os.environ[k])
        self.log.debug('Environment : %s' %envmsg)

    def __platforminfo(self):
        '''
        display basic info about the platform, for debugging purposes 
        '''
        self.log.info('platform: uname = %s %s %s %s %s %s' %platform.uname())
        self.log.info('platform: platform = %s' %platform.platform())
        self.log.info('platform: python version = %s' %platform.python_version())
        self._printenv()

    def __checkroot(self): 
        """
        If running as root, drop privileges to --runas' account.
        """
        starting_uid = os.getuid()
        starting_gid = os.getgid()
        starting_uid_name = pwd.getpwuid(starting_uid)[0]

        hostname = socket.gethostname()
        
        if os.getuid() != 0:
            self.log.info("Already running as unprivileged user %s at %s" % (starting_uid_name, hostname))
            
        if os.getuid() == 0:
            try:
                runuid = pwd.getpwnam(self.options.runAs).pw_uid
                rungid = pwd.getpwnam(self.options.runAs).pw_gid
                os.chown(self.options.logfile, runuid, rungid)
                
                os.setgid(rungid)
                os.setuid(runuid)
                os.seteuid(runuid)
                os.setegid(rungid)

                self._changehome()
                self._changewd()

                self.log.info("Now running as user %d:%d at %s..." % (runuid, rungid, hostname))
                self._printenv()

            
            except KeyError, e:
                self.log.error('No such user %s, unable run properly. Error: %s' % (self.options.runAs, e))
                sys.exit(1)
                
            except OSError, e:
                self.log.error('Could not set user or group id to %s:%s. Error: %s' % (runuid, rungid, e))
                sys.exit(1)

    def _changehome(self):
        '''
        Set environment HOME to user HOME.
        '''
        runAs_home = pwd.getpwnam(self.options.runAs).pw_dir 
        os.environ['HOME'] = runAs_home
        self.log.debug('Setting up environment variable HOME to %s' %runAs_home)


    def _changewd(self):
        '''
        changing working directory to the HOME directory of the new user,
        '''
        runAs_home = pwd.getpwnam(self.options.runAs).pw_dir
        os.chdir(runAs_home)
        self.log.debug('Switching working directory to %s' %runAs_home)


    def __createconfig(self):
        """Create config, add in options...
        """
        if self.options.confFiles != None:
            try:
                self.config = ConfigParser()
                self.config.read(self.options.confFiles)
            except Exception, e:
                self.log.error('Config failure')
                sys.exit(1)
        
        #self.config.set("global", "configfiles", self.options.confFiles)
           
    def run(self):
        """
        Create Daemon and enter main loop
        """

        try:
            self.log.info('Creating Daemon and entering main loop...')
            vc3m = VC3Master(self.config)
            vc3m.run()
            
            while True:
                time.sleep(2)
            
        except KeyboardInterrupt:
            self.log.info('Caught keyboard interrupt - exitting')
            vc3m.shutdown()
            sys.exit(0)
        
        except ImportError, errorMsg:
            self.log.error('Failed to import necessary python module: %s' % errorMsg)
            vc3m.shutdown()
            sys.exit(1)
        
        except:
            self.log.error('''Unexpected exception!''')
            # The following line prints the exception to the logging module
            self.log.error(traceback.format_exc(None))
            print(traceback.format_exc(None))
            try:
                vc3m.shutdown()
            except UnboundLocalError:
                self.log.error('''Master did not even start''')
            sys.exit(1)          

if __name__ == '__main__':
    mcli = VC3MasterCLI()
    mcli.run()

