'''
  Dynamic plugin to simply execute on local host via command line. 
'''

import logging


class Execute(object):

    def __init__(self, parent, config, section):
        self.log = logging.getLogger()    
        self.parent = parent
        self.config = config
        self.section = section    
        self.running = []
        self.log.debug("Execute dynamic plugin initialized.")
        
        
    def launch(self, name, config=None, cmd=None):
        '''
        Launches a process using the command given. Stores info about the 
        process indexed by <name> for later action. 
        
        '''
        
        
    def terminate(self, name):
        '''
        Terminates the process with label <name>
        
        '''
    