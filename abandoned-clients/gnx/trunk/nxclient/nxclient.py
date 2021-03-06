#!/usr/bin/python
# -*- coding: utf-8 -*-

# nxclient.py -- a simple client for FreeNX
#
# Copyright (C) 2005 Instituto de Estudos e Pesquisas dos Trabalhadores
# no Setor Energético, Marco Sinhoreli and Gustavo Noronha Silva
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
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

# i18n will come!
def _ (x):
    return x

import os, sys
import pexpect

from pexpect import EOF, TIMEOUT

CLIENTID = 'NXCLIENT - Version 1.4.0'
HOME = os.getenv ('HOME')

class SSHAuthError(Exception):
    """
    Attributes:

    errtype - key missing, auth failed?
    message - message explaining the problem

    errtype can be:
     0: the ssh private key is not accessible
     1: the ssh key authentication failed
    """
    
    def __init__ (self, errtype, message):
        self.errtype = errtype
        self.message = message

class SSHConnectionError(Exception):
    """
    Attributes:

    errtype - key missing, auth failed?
    message - message explaining the problem

    errtype can be:
     0: connection refused (port closed, for example)
    """
    
    def __init__ (self, errtype, message):
        self.errtype = errtype
        self.message = message

class ProtocolError(Exception):
    """
    Attributes:

    message - message explaining the problem
    """
    
    def __init__ (self, message):
        self.message = message

class NXProxyError(Exception):
    """
    Attributes:

    errtype - type of the error, can be:
              0: failed on creating directories or the
                 options file
    message - message explaining the problem
    """

    def __init__ (self, errtype, message):
        self.errtype = errtype
        self.message = message

# state of the connection
NOTCONNECTED = 0
CONNECTING = 1
CONNECTED = 2
STARTING = 3
RUNNING = 4

class NXClient:
    """
    NXClient class

    Instantiation:

    NXClient (config)

    * config is an instance of NXConfig

    Attributes:

    log:         file object to which the session log will be written
                 to, stdout is default

    connection:  file object used to communicate with the nxserver
    state:       state of the connection, one of the following:
                    NOTCONNECTED - nothing happened or connection
                                   was closed
                    CONNECTING   - ssh connection being stabilished
                                   and user authorization being
                                   negotiated with nxserver
                    CONNECTED    - ready to list for active sessions
                                   and start/restore sessions

    Methods:

    connect ():       starts the connection by connecting to the
                      host through nxssh and authenticating the
                      user with nxserver

    Frontend Facilities:

    yes_no_dialog (): asks the user a yes/no question
    
    """

    def __init__ (self, config):
        self.config = config
        
        self.log = sys.stdout

        self.state = NOTCONNECTED

        if not os.access (config.sshkey, os.R_OK):
            raise SSHAuthError (0, _('SSH key is inaccessible.'))

    def connect (self):
        try:
            self._connect ()
        except:
            self._set_state (NOTCONNECTED)

    def _waitfor (self, code):
        connection = self.connection
        
        if code: size = len (code)
        else: size = 3

        found = False
        while not found:
            try:
                connection.expect (['NX> '])
                remote_code = connection.read (size)
                if not code or remote_code == code:
                    found = True
            except TIMEOUT, EOF:
                message = remote_code + connection.readline ()
                raise ProtocolError (_('Protocol error: %s') % \
                                     (message))

    def disconnect (self):
        connection = self.connection
        connection.send ('\n')
        self._set_state (NOTCONNECTED)

    def _connect (self):
        host = self.config.host
        port = self.config.port
        username = self.config.username
        password = self.config.password
        sshkey = self.config.sshkey

        self._set_state (CONNECTING)
        waitfor = self._waitfor
        
        connection = pexpect.spawn ('nxssh -nx -p %d -i %s nx@%s -2 -S' % \
                                    (port, sshkey, host))
        self.connection = connection
        connection.setlog (self.log)

        send = connection.send

        try:
            choice = 1
            while choice != 0:
                choice = connection.expect (['HELLO', 'NX> 204 ', 'nxssh: ', 'NX> 205 '])
                if choice == 0:
                    waitfor ('105')
                    send ('HELLO NXCLIENT - Version 1.4.0\n')
                elif choice == 1:
                    raise SSHAuthError (1, _('SSH key authentitcation failed.'))
                elif choice == 2:
                    raise SSHConnectionError (0, _('Connection refused.'))
                elif choice == 3:
                    # FIXME: should get the fingerprint and show a i18n'ed
                    # message
                    msg = connection.readline ()
                    connection.expect ('\?')
                    msg += connection.before + '?'
                    
                    if self._yes_no_dialog (msg):
                        send ('yes\n')
                    else:
                        send ('no\n')
                        self._set_state (NOTCONNECTED)
            del choice

            # check if protocol was accepted
            waitfor ('134')

            # wait for the shell
            waitfor ('105')
            send ('login\n')

            # user prompt
            waitfor ('101')
            send (username + '\n')

            # password prompt
            waitfor ('102')
            send (password + '\n')

            # check if all went fine
            waitfor (None)
            if connection.after[:3] == '404':
                raise ProtocolError (_('Failed to login: wrong username or password given. (404)'))
            elif connection.after[:3] != '103':
                raise ProtocolError (_('Protocol error: %s') % \
                                     (connection.after))

            # ok, we're in
            waitfor ('105')
            self._set_state (CONNECTED)
            
        except (EOF, TIMEOUT):
            # raise our own?
            raise

    # FIXME: LOADS of error-checking missing, should not
    # block on os.system()
    def start_session (self):
        host = self.config.host
        session = self.config.session

        waitfor = self._waitfor
        connection = self.connection

        # FIXME: raise exception?
        if not session:
            return 1

        self._set_state (STARTING)

        send = connection.send
        send ('startsession %s\n' % (session.get_start_params ()))

        waitfor ('700')
        line = connection.readline ()
        session.id = line.split (':', 2)[1].strip ()

        waitfor ('705')
        line = connection.readline ()
        session.display = line.split (':', 2)[1].strip ()

        waitfor ('701')
        line = connection.readline ()
        session.pcookie = line.split (':', 2)[1].strip ()

        waitfor ('1006')
        line = connection.readline ()
        session.status = line.split (':', 2)[1].strip ()

        try:
            os.mkdir ('%s/.nx/S-%s' % (HOME, session.id))
            f = open ('%s/.nx/S-%s/options' % (HOME, session.id), 'w')
            f.write ('cookie=%s,root=%s/.nx,session=%s,id=%s,connect=%s:%s' % \
                     (session.pcookie, HOME, session.sname, session.id, \
                      host, session.display))
            f.close ()
        except OSError, e:
            raise NXProxyError (0, e.strerror)

        self._set_state (RUNNING)

        os.system ('nxproxy -S options=%s/.nx/S-%s/options:%s > /dev/null 2>&1' % \
                   (HOME, session.id, session.display))

    def _set_state (self, state):
        self.state = state
        self._update_connection_state (state)

    # Frontend Facilities
    def _yes_no_dialog (self, msg):
        response = raw_input (msg).strip ()
        if response == 'yes':
            return True
        else:
            return False

    def _update_connection_state (self, state):
        pass

if __name__ == '__main__':
    from nxconfig import NXConfig
    from nxsession import NXSession

    host = raw_input ('Host: ')
    port = raw_input ('Port: ')
    user = raw_input ('User: ')
    password = raw_input ('Password: ')
    session_type = raw_input ('Session type: ')

    config = NXConfig (host, user, password)
    nc = NXClient (config)

    nc.connect ()

    nc.session = NXSession ('teste-gnome')
    nc.session.session_type = session_type
    nc.start_session ()

    nc.connection.send ('\n')
