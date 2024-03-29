#!/usr/bin/env python3

"""
Script that uses a BlinkStick (http://www.blinkstick.com/) to provide a 
visual indication of the status of an LWA station through a series of 
flashes.  The flashes shown are:
  ~1 second of green, yellow, or red for the overall station status with:
    green - All subsystems are normal
    yellow - No errors conditions but not all subsystems are normal
    red - One or more subsystems are in error 
    
  ~0.25 seconds of blue, green, or purple for each DR that is not idle with:
    blue - spectrometer mode
    green - raw data recording mode

In addition, the station information is displayed on the running terminal.
"""


import re
import sys
import json
import time
import curses
import string
from urllib.request import urlopen
import argparse
import threading
from datetime import datetime, timedelta
from blinkstick import blinkstick


# RegEx for parsing out the DR OP-TYPE from the OpScreen page
drRE = re.compile(r'\<tr\>\<td\>DR(?P<N>\d)\<\/td\>')


# Template for the curses output
display = {}

display[2] = string.Template("""Overall Status of $station:
$sysStatus

Operation Types:
  DR1: $optype1
  DR2: $optype2

LASI:
  $lasiStatus

Updated: $tUpdate UTC
""")

display[3] = string.Template("""Overall Status of $station:
$sysStatus

Operation Types:
  DR1: $optype1
  DR2: $optype2
  DR3: $optype3

LASI:
  $lasiStatus

Updated: $tUpdate UTC
""")

display[4] = string.Template("""Overall Status of $station:
$sysStatus

Operation Types:
  DR1: $optype1
  DR2: $optype2
  DR3: $optype3
  DR4: $optype4

LASI:
  $lasiStatus

Updated: $tUpdate UTC
""")

display[5] = string.Template("""Overall Status of $station:
$sysStatus

Operation Types:
  DR1: $optype1
  DR2: $optype2
  DR3: $optype3
  DR4: $optype4
  DR5: $optype5

LASI:
  $lasiStatus

Updated: $tUpdate UTC
""")


class PollStation(object):
    """
    Class for polling the station status in the background at the specified 
    interval in seconds.
    """
    
    def __init__(self, station, lwatv_channel, ndr, pollInterval=180):
        self.station = station
        self.lwatv_channel = lwatv_channel
        self.ndr = ndr
        self.pollInterval = float(pollInterval)
        
        # Attributes to store the station status
        self.lastUpdate = datetime.utcnow() - timedelta(minutes=30)
        self.systemStatus = 0
        self.opTypes = [0,]*self.ndr
        self.lasiRunning = False
        
        # Setup threading
        self.thread = None
        self.alive = threading.Event()
        self.lock = threading.Lock()
        
    def start(self):
        if self.thread is not None:
            self.stop()
            
        self.thread = threading.Thread(target=self.monitor, name='monitor')
        self.thread.setDaemon(1)
        self.alive.set()
        self.thread.start()
        time.sleep(5)
        
    def stop(self):
        if self.thread is not None:
            self.alive.clear()          #clear alive event for thread
            
            self.thread.join()          #don't wait too long on the thread to finish
            self.thread = None
            
    def monitor(self):
        """
        Get the current state of the LWA station from the OpScreen page.  This 
        function returns a four element tuple of status update time time as a 
        datetime instance, the overall station status, a ndr-element list of 
        DR OP-TYPEs, and a boolean for if LASI is running or not.
        
        The station status and OP-TYPEs are expressed a integers.  The values 
        are:
        Station Status
        0 - One or more subsystems are in error 
        1 - No errors conditions but not all subsystems are normal
        2 - All subsystems are normal
        
        DR OP-TYPE
        0 - Idle
        1 - Spectrometer mode
        2 - Raw data recording mode
        """
        
        while self.alive.isSet():
            tStart = time.time()
            
            # Update time
            tNow = datetime.utcnow()
            
            # Default values
            sysStatus = 0
            opType = [0 for i in range(self.ndr)]
            lasi = False
            
            try:
                # Fetch the OpScreen page
                with urlopen('http://lwalab.phys.unm.edu/OpScreen/%s/status.json' % self.station) as uh:
                    output = json.loads(uh.read())
                    
                # Parse
                sysStatus = 2
                opType = [0 for i in range(self.ndr)]
                for entry in output:
                    ## Station status
                    if entry['setting'] == 'SUMMARY':
                        if entry['value'] in ('WARNING', 'SHUTDWN') and sysStatus > 1:
                            sysStatus = 1
                        if entry['value'] == 'ERROR' and sysStatus > 0:
                            sysStatus = 0
                            
                    ## DR OP-TYPEs
                    if entry['subsystem'].startswith('DR') and entry['setting'] == 'OP_TYPE':
                        n = int(entry['subsystem'][2:], 10) - 1
                        if entry['value'] == 'Record':
                            opType[n] = 2
                        elif entry['value'] == 'Spectrometr':
                            opType[n] = 1
                            
                # Figure out if LASI is running
                with urlopen("http://lwalab.phys.unm.edu/%s/lwatv.png" % self.lwatv_channel) as uh:
                    info = uh.info()
                    data = uh.read()
                    
                lm = info.get("last-modified")
                lm = datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT")
                age = datetime.utcnow() - lm
                age = age.days*24*3600 + age.seconds
                
                # Is the image recent enough to think that TBN/LASI is running?
                if age < 120:
                    lasi = True
                    
                # Update
                self.lock.acquire()
                self.lastUpdate = tNow
                self.systemStatus = sysStatus
                self.opTypes = opType
                self.lasiRunning = lasi
                self.lock.release()
            except Exception as e:
                pass
                
            # Main loop stop time
            tStop = time.time()
            
            # Pause before the next monitoring update
            sleepCount = 0.0
            sleepTime = self.pollInterval - (tStop - tStart)
            while (self.alive.isSet() and sleepCount < sleepTime):
                time.sleep(0.2)
                sleepCount += 0.2
                
    def getStatus(self):
        """
        Get the current state of LWA1 from the OpScreen page.  This function
        returns a four element tuple of status update time time as a datetime
        instance, the overall station status, a five-element list of DR 
        OP-TYPEs, and a boolean for if LASI is running or not.
        
        The station status and OP-TYPEs are expressed a integers.  The values are:
        Station Status
        0 - One or more subsystems are in error 
        1 - No errors conditions but not all subsystems are normal
        2 - All subsystems are normal
        
        DR OP-TYPE
        0 - Idle
        1 - Spectrometer mode
        2 - Raw data recording mode
        """
        
        self.lock.acquire()
        output = (self.lastUpdate, self.systemStatus, self.opTypes, self.lasiRunning)
        self.lock.release()
        
        return output


def restorescreen():
    """
    Function to restore the screen after curses has finished.
    """
    
    curses.nocbreak()
    curses.echo()
    curses.endwin()


def getDisplayInformation(tNow, stationName, sysStatus, opType, lasi):
    """
    Given the output of getStatus(), generate the curses display string.
    """
    
    # Station status
    subs = {'station': stationName.upper()}
    if sysStatus == 0:
        subs['sysStatus'] = 'One or more subsystems in error                       '
    elif sysStatus == 1:
        subs['sysStatus'] = 'No errors conditions but not all subsystems are normal'
    else:
        subs['sysStatus'] = 'All subsystems are normal                             '
        
    # DR OP-TYPEs
    for i in range(len(opType)):
        key = 'optype%i' % (i+1)
        if opType[i] == 0:
            subs[key] = 'Idle        '
        elif opType[i] == 1:
            subs[key] = 'Spectrometer'
        else:
            subs[key] = 'Recording   '
            
    # LASI status
    subs['lasiStatus'] = 'Running    ' if lasi else 'Not running'
    
    # Update time
    subs['tUpdate'] = tNow.strftime("%Y/%m/%d %H:%M:%S")
    
    # Done
    return display[len(opType)].safe_substitute(subs)


def main(args):
    if args.lwana:
        station = 'lwana'
        lwatv_channel = 'lwatv4'
        ndr = 4
    elif args.lwasv:
        station = 'lwasv'
        lwatv_channel = 'lwatv2'
        ndr = 4
    else:
        ## Default to LWA1
        station = 'lwa1'
        lwatv_channel = 'lwatv'
        ndr = 5
        
    # Setup the BlinkStick
    bs = blinkstick.find_first()
    print(f"Using: {bs.get_serial()}")
    
    # Integer -> LED color conversion list
    ssColors = ['red', 'orange', 'green']
    otColors = ['black', 'blue', 'green']
    
    # Start the background task
    poll = PollStation(station, lwatv_channel, ndr,
                       pollInterval=180)
    poll.start()
    
    try:
        # Setup display screen
        screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        screen.nodelay(1)
        
        # Get the latest information from the OpScreen page
        t0 = time.time()
        tNow, sysStatus, opType, lasi = poll.getStatus()
        
        # Refresh screen
        screen.clear()
        screen.addstr(0,0,getDisplayInformation(tNow, station, sysStatus, opType, lasi))
        screen.refresh()
        
        # Go!
        while True:
            ## Check the time to see if we need to update the status.  This happens
            ## once every ~3 minutes to keep the load on lwalab down.
            t1 = time.time()
            if t1-t0 > 30:
                # Update
                t0 = time.time()
                tNow, sysStatus, opType, lasi = poll.getStatus()
                
                # Refresh screen
                screen.clear()
                screen.addstr(0,0,getDisplayInformation(tNow, station, sysStatus, opType, lasi))
                
            ## Blink out the station status
            try:
                bs.pulse(name=ssColors[sysStatus], repeats=1, duration=1000)
                time.sleep(0.25)
            except IOError:
                pass
                
            ## Blink out the DR OP-TYPEs as needed
            for ot in opType:
                # Skip Idle DRs
                if ot == 0:
                    continue
                    
                # Blink
                try:
                    bs.pulse(name=otColors[ot], repeats=1, duration=250)
                    time.sleep(0.25)
                except IOError:
                    pass
                    
            # Blink the LASI status
            if lasi:
                try:
                    bs.pulse(name='purple', repeats=1, duration=250)
                    time.sleep(0.25)
                except IOError:
                    pass
                    
            ## Check for keypress and exit if Q or q
            c = screen.getch()
            if (c > 0):
                if chr(c) == 'q': 
                    break
                if chr(c) == 'Q': 
                    break
                    
    except KeyboardInterrupt:
        pass        
        
    except Exception as e:
        exitException = str(e)
        
    # Save the window contents
    contents = ''
    y,x = screen.getmaxyx()
    for i in range(y-1):
        for j in range(x):
            d = screen.inch(i,j)
            c = d&0xFF
            a = (d>>8)&0xFF
            contents += chr(c)
            
    # Finished with the poll-update loop.  Reset the screen and turn off 
    # the blinkstick
    restorescreen()
    bs.turn_off()
    poll.stop()
    
    # Report on any exception that may have caused the main loop to exit
    try:
        print(f"Error: {str(exitException)}")
    except NameError:
        ## Last window contents sans attributes
        print(contents)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
            description="Blink out the status of an LWA station using a BlinkStick",
            )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--lwa1', action='store_true',
                        help='report on LWA1')
    group.add_argument('--lwasv', action='store_true',
                       help='report on LWA-SV')
    group.add_argument('--lwana', action='store_true',
                       help='report on LWA-NA')
    args = parser.parse_args()
    main(args)
        
