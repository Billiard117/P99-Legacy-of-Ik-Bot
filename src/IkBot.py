import asyncio
import os
import random
import re
import threading
import time
from datetime import datetime
from typing import Self

import discord
import pygsheets
import pytz
from discord.ext import commands

# import the customized settings and file locations etc, found in myconfig.py
import myconfig

# allow for testing, by forcing the bot to read an old log file for the VT and VD fights
TEST_BOT = False
# TEST_BOT                = True

# Set Variables
CST = pytz.timezone('US/Central')

# Google sheets integration
gc = pygsheets.authorize(service_account_json=myconfig.GOOGLE_SHEETS_KEY)
ikbot_sheet  = gc.open('IkBot')

roster_sheet = ikbot_sheet.worksheet_by_title('Roster')
target_sheet = ikbot_sheet.worksheet_by_title('Targets')
item_sheet   = ikbot_sheet.worksheet_by_title('Items')
taunt_Sheet  = ikbot_sheet.worksheet_by_title('Taunts')
trade_sheet  = ikbot_sheet.worksheet_by_title('Trade')

#################################################################################################

#
# class to encapsulate log file operations
#
class EverquestLogFile:

    # list of regular expressions matching log files indicating the 'target' is spawned and active
    trigger_list = [
        '^(.+) (have|has) been slain by',
        '^(.+) (have|has) slain',
        '^Players (on|in) EverQuest:',
        '^(.+)<Legacy of Ik>',
        '^There (is|are) . (player|players) in',
        '^You have entered (?!an Arena)',
        '^--(\w)+ (have|has) looted a',
        '^You have gained a level! Welcome to level ',
        '^You have become better at (.+)!',
        # '^You have become better at (.+)! \((1|2)(5|0)0\)',
        '^(\w)+ tells you, \'Attacking (.+) Master.\''
    ]

    target_list  = [cell[0] for cell in target_sheet.range('A2:A', returnas='matrix')]
    item_list    = [cell[0] for cell in item_sheet.range('A2:A', returnas='matrix')]
    trade_list   = [cell[0] for cell in trade_sheet.range('A2:A', returnas='matrix')]
    roster_list  = [cell[0] for cell in roster_sheet.range('A2:A', returnas='matrix')]

    # General Variables
    my_zone = 'Unknown'
    my_level ='1'
    my_pet = 'Unknown'
    tradeskills_dict = {}
    tradeskills_string = ''

    #
    # ctor
    #

    def __init__(self, char_name=myconfig.DEFAULT_CHAR_NAME):

        # instance data
        self.base_directory = myconfig.BASE_DIRECTORY
        self.logs_directory = myconfig.LOGS_DIRECTORY
        self.char_name = char_name
        self.server_name = myconfig.SERVER_NAME
        self.filename = ''
        self.file = None

        self.parsing = threading.Event()
        self.parsing.clear()

        self.author = ''

        self.prevtime = time.time()
        self.heartbeat = myconfig.HEARTBEAT

        # timezone string for current computer
        self.current_tzname = time.tzname[time.daylight]

        # build the filename
        self.build_filename()

    # build the file name
    # call this anytime that the filename attributes change
    def build_filename(self):
        self.filename = self.base_directory + self.logs_directory + \
            'eqlog_' + self.char_name + '_' + self.server_name + '.txt'

    # def build_filename(self):
    #    self.loglocation = self.base_directory + self.logs_directory
    #    while True: #checking for an active log
    #        try:
    #            max([f for f in os.scandir(self.loglocation)], key=lambda x: x.stat().st_mtime).name
    #            break
    #        except ValueError:
    #            print('No Active Logs Found, retrying in 5s..')
    #            time.sleep(5)
    #    self.filename = max([f for f in os.scandir(self.loglocation)], key=lambda x: x.stat().st_mtime).name
    #    while (self.filename == 'dbg.txt'): #checking for an active log
    #        print('No Active Logs Found, retrying in 5s..')
    #        time.sleep(5)
    #        self.filename = max([f for f in os.scandir(self.loglocation)], key=lambda x: x.stat().st_mtime).name
    #    print(self.filename)

    # is the file being actively parsed
    def set_parsing(self):
        self.parsing.set()

    def clear_parsing(self):
        self.parsing.clear()

    def is_parsing(self):
        return self.parsing.is_set()

    # open the file
    # seek file position to end of file if passed parameter 'seek_end' is true
    def open(self, author, seek_end=True):
        try:
            self.file = open(self.filename)
            if seek_end:
                self.file.seek(0, os.SEEK_END)
            self.author = author
            self.set_parsing()
            return True
        except Exception:
            return False

    # close the file
    def close(self):
        self.file.close()
        self.author = ''
        self.clear_parsing()

    # get the next line
    def readline(self):
        if self.is_parsing():
            return self.file.readline()
        else:
            return None

    # regex match?
    def regex_match(self, line):
        event = None
        # cut off the leading date-time stamp info
        trunc_line = line[27:]
        # walk thru the target list and trigger list and see if we have any match
        for trigger in self.trigger_list:
            if re.match(trigger, trunc_line):
                # DEATH
                if 'You have been slain' in trunc_line:
                    mob = trunc_line.index('by ')+3, trunc_line.index("\n")
                    event = 'SelfDeath', trunc_line[mob[0]:mob[1]]

                #Roster Updates
                elif re.match('^Players (on|in) EverQuest:', trunc_line):
                    elf.roster_list = [cell[0] for cell in roster_sheet.range('A:A', returnas='matrix')]
                    return None
                elif '<Legacy of Ik>' in trunc_line:
                    char = self.parse_who_string(trunc_line)
                    return self.update_roster(char)
                # elif re.match('^There (is|are) . (player|players) in', trunc_line):
                    # roster_Sheet.sort_range('A2', 'K100', basecolumnindex=5, sortorder='DESCENDING')

                # Level Parsing
                elif 'You have gained a level! Welcome to level' in trunc_line:
                    self.my_level = int(trunc_line[-4:-1].strip('!'))
                    if self.my_level % 5 == 0 and self.my_level > 9:
                        return ['LevelUp', elf.char_name, self.my_level]

                # ZONE Tracking
                elif 'You have entered ' in trunc_line:
                    self.my_zone = trunc_line[17:trunc_line.index(".")]

                # Pet Parsing
                elif re.match('^(\w)+ tells you, \'Attacking (.+) Master.\'', trunc_line):
                    self.my_pet = trunc_line[:trunc_line.index(' tells')]

                # Kill Parsing Self / Pet / Ik Member
                elif 'You have slain ' in trunc_line:
                    if event := [['Kill', elf.char_name, target]
                                 for target in self.target_list if target in trunc_line]:
                        return event[0]
                elif ' has been slain by ' in trunc_line:
                    if event := [['Kill', elf.char_name, target]
                                 for target in self.target_list
                                 if elf.my_pet in trunc_line and target in trunc_line]:
                        return event[0]
                    if event := [['Kill', member, target]
                                 for member in self.roster_list for target in self.target_list
                                 if member in trunc_line and target in trunc_line]:
                        return event[0]

                # Loot Parsing
                elif 'You have looted a' in trunc_line:
                    if event := [['Loot', elf.char_name, item]
                                 for item in self.item_list if item in trunc_line]:
                        return event[0]
                elif 'has looted a' in trunc_line:
                    if event := [['Loot', member, item]
                                 for member in self.roster_list for item in self.item_list
                                 if member in trunc_line and item in trunc_line]:
                        return event[0]

                # Tradeskills
                elif 'You have become better at ' in trunc_line:
                    skill = int(trunc_line[-5:trunc_line.index(")")].strip('( '))
                    for trade in self.trade_list:
                        if trade in trunc_line and skill > 24:
                            if not self.tradeskills_dict:
                                print('nodict')
                                self.tradeskills_string = roster_sheet.cell((roster_sheet.find(self.char_name)[0].row, roster_sheet.find('Tradeskills')[0].col)).value
                                if self.tradeskills_string:
                                    print('Building dict from string')
                                    self.tradeskills_dict = {x.strip(): y.strip() for x, y in (element.split(' ') for element in self.tradeskills_string.split(' / '))}
                            self.tradeskills_dict.update({trade: f'({skill})'})
                            if skill % 50 == 0:
                                event = 'Trade', trade, skill

        # only executes if loops did not return already
        return event

    # Build character roster entry
    def parse_who_string(self, whoStr):
        ind = whoStr.index('] '), whoStr.index(' ('), whoStr.index(' ')
        char = [whoStr[ind[0]+2:ind[1]], whoStr[ind[2]+1:ind[0]], whoStr[1:ind[2]], '', datetime.now(CST).strftime("%m/%d/%Y")]
        if zone_update := 'ZONE:' in whoStr:
            z_ind = whoStr.index(': ')+2, whoStr.index("\n")-2
            char[3] = whoStr[z_ind[0]:z_ind[1]]
        else:
            char[3] = self.my_zone

        if char[0] == self.char_name:
            self.my_level = char[2]
            if zone_update:
                self.my_zone = char[3]
            if self.tradeskills_dict:
                char.append(' / '.join(' '.join((key, val)) for (key, val) in self.tradeskills_dict.items()))
        return char

    # Update the Roster
    def update_roster(self, char):
        if char[0] in self.roster_list:
            # Update existing member
            cell = roster_sheet.find(char[0])
            roster_sheet.update_row(cell[0].row, char[2:], col_offset=2)
            event = 'Update', char[0]
        else:
            # Add new member
            roster_sheet.append_table(values=char)
            self.roster_list = [cell[0] for cell in roster_sheet.range('A:A', returnas='matrix')]
            event = 'New', char[0]
        return event


# create the global instance of the log file class
elf = EverquestLogFile()

#################################################################################################

# the background process to parse the log files
#
# override the run method
#


async def parse():
    
    print('Parsing Started')
    print('Make sure to turn on logging in EQ with /log command!')

    # process the log file lines here
    while elf.is_parsing() == True:
        # read a line
        line = elf.readline()
        now = time.time()
        if line:
            #time.sleep(.05)
            elf.prevtime = now
            print(line, end='')

            # does it match a trigger?
            if event := elf.regex_match(line):
                time.sleep(.5)
                #print(event)
                # Discord Bot Triggers
                # Level Up
                if 'LevelUp' in event[0]:
                    await client.alarm(f'{event[1]} has reached level {event[2]}! Now get back to work!')

                # Self Death
                elif 'SelfDeath' in event[0]:
                    taunt_death = taunt_Sheet.range('B:B', returnas='matrix')
                    await client.alarm(f'{elf.char_name} has fallen to {event[1]}! {random.choice(taunt_death)[0]}')

                # Roster Updates
                elif 'New' in event[0]:
                    taunt_new_member = taunt_Sheet.range('A:A', returnas='matrix')
                    await client.alarm(f'Bahaha! {event[1]} has pledged their life to the Legacy! {random.choice(taunt_new_member)[0]}')

                # Tradeskill Milestones
                elif 'Trade' in event[0]:
                    quip_loc = f'B{str(elf.trade_list.index(event[1]) + 1)}'
                    await client.alarm(f'{event[2]} {event[1]}! Pretty impressive {elf.char_name}. {trade_sheet.get_value(quip_loc)}')

                # Notable Kills
                elif 'Kill' in event[0]:
                    await client.alarm(f'{event[1]} just killed {event[2]}! **FOR IK!** Any good loot?')

                # Notable Loot
                elif 'Loot' in event[0]:
                    await client.alarm(f"{event[1]} just looted a {event[2]} for me! Leave it with the War Baron and he\'ll get it to me.")

        else:
            # check the heartbeat.  Has our tracker gone silent?
            elapsed_minutes = (now - elf.prevtime)/60.0
            if elapsed_minutes > elf.heartbeat:
                elf.prevtime = now
                print(
                    f'Heartbeat Warning:  Tracker [{elf.char_name}] logfile has had no new entries in last {elf.heartbeat} minutes.  Is {elf.char_name} still online?')

            await asyncio.sleep(0.1)

    print('Parsing Stopped')


#################################################################################################


# define the client instance to interact with the discord bot

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

class myClient(commands.Bot):
    def __init__(self):
        commands.Bot.__init__(
            self, command_prefix=myconfig.BOT_COMMAND_PREFIX, intents=intents)

    # sound the alarm
    async def alarm(self, msg):
        logging_channel = client.get_channel(myconfig.DISCORD_SERVER_CHANNELID)
        await logging_channel.send(msg)

        print(f'Alarm:{msg}')


# create the global instance of the client that manages communication to the discord bot
client = myClient()

#################################################################################################


#
# add decorator event handlers to the client instance
#

# on_ready
@client.event
async def on_ready():
    print('FOR IK!')
    print(f'Discord.py version: {discord.__version__}')

    print(f'Logged on as {client.user}!')
    print(f'App ID: {client.user.id}')

    await auto_start()


# on_message - catches everything, messages and commands
# note the final line, which ensures any command gets processed as a command, and not just absorbed here as a message
@client.event
async def on_message(message):
    author = message.author
    content = message.content
    channel = message.channel
    print(
        f'Content received: [{content}] from [{author}] in channel [{channel}]')
    await client.process_commands(message)


#################################################################################################


async def auto_start():
    # await client.connect()
    # await client.login(myconfig.BOT_TOKEN)
    # print("Auto start")
    # print('Command received: [{}] from [{}]'.format(ctx.message.content, ctx.message.author))
    elf.char_name = myconfig.DEFAULT_CHAR_NAME
    elf.build_filename()

    author = myconfig.DEFAULT_CHAR_NAME

    # open the log file to be parsed
    # allow for testing, by forcing the bot to read an old log file for the VT and VD fights
    if TEST_BOT is False:
        # start parsing.  The default behavior is to open the log file, and begin reading it from tne end, i.e. only new entries
        rv = elf.open(author)
    else:
        # use a back door to force the system to read files from the beginning that contain VD / VT fights to test with
        elf.filename = elf.base_directory + elf.logs_directory + 'test_fights.txt'

        # start parsing, but in this case, start reading from the beginning of the file, rather than the end (default)
        rv = elf.open(author, seek_end=False)

    # if the log file was successfully opened, then initiate parsing
    if rv:
        # status message
        print(f'Now parsing character log for: [{elf.char_name}]')
        print(f'Log filename: [{elf.filename}]')
        print(f'Parsing initiated by: [{elf.author}]')
        print(f'Heartbeat timeout (minutes): [{elf.heartbeat}]')

        # create the background processs and kick it off
        client.loop.create_task(parse())
    else:
        print(
            f'ERROR: Could not open character log file for: [{elf.char_name}]')
        print(f'Log filename: [{elf.filename}]')


# let's go!!
client.run(myconfig.BOT_TOKEN)
