##########################################################################
#

#   MRC FGU Computational Genomics Group
#
#   $Id$
#
#   Copyright (C) 2009 Andreas Heger
#
#   This program is free software; you can redistribute it and/or
#   modify it under the terms of the GNU General Public License
#   as published by the Free Software Foundation; either version 2
#   of the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
##########################################################################
'''
Experiment.py - Tools for scripts
=================================

:Author: Andreas Heger
:Release: $Id$
:Date: |today|
:Tags: Python

The :mod:`Experiment` modules contains utility functions for logging
and record keeping of scripts.

This module is imported by most CGAT scripts. It provides convenient
and consistent methods for

   * `Record keeping`_
   * `Benchmarking`_

See :doc:`../scripts/cgat_script_template` on how to use this module.

The basic usage of this module within a script is::

    """script_name.py - my script
    
    Mode Documentation
    """
    import sys
    import optparse
    import CGAT.Experiment as E

    def main( argv = None ):
        """script main.

        parses command line options in sys.argv, unless *argv* is given.
        """

        if not argv: argv = sys.argv

        # setup command line parser
        parser = E.OptionParser( version = "%prog version: $Id$", 
                                        usage = globals()["__doc__"] )
                                        
        parser.add_option("-t", "--test", dest="test", type="string",
                          help="supply help"  )

        ## add common options (-h/--help, ...) and parse command line 
        (options, args) = E.Start( parser )

        # do something
        # ...
        E.info( "an information message" )
        E.warn( "a warning message")

        ## write footer and output benchmark information.
        E.Stop()

    if __name__ == "__main__":
        sys.exit( main( sys.argv) )


Record keeping
--------------

The central functions in this module are the :py:func:`Start` and
:py:func:`Stop` methods which are called before or after any work is done 
within a script.

.. autofunction:: Experiment.Start

The :py:func:`Start` is called with an E.OptionParser object. 
:py:func:`Start` will add additional command line arguments, such as
``--help`` for command line help or ``--verbose`` to control the :term:`loglevel`.
It can also add optional arguments for scripts needing database access,
writing to multiple output files, etc. 

:py:func:`Start` will write record keeping information to a logfile. Typically, logging
information is output on stdout, prefixed by a `#`, but it can be re-directed to 
a separate file. Below is a typical output::

    # output generated by /ifs/devel/andreas/cgat/beds2beds.py --force --exclusive --method=unmerged-combinations --output-filename-pattern=030m.intersection.tsv.dir/030m.intersection.tsv-%s.bed.gz --log=030m.intersection.tsv.log Irf5-030m-R1.bed.gz Rela-030m-R1.bed.gz
    # job started at Thu Mar 29 13:06:33 2012 on cgat150.anat.ox.ac.uk -- e1c16e80-03a1-4023-9417-f3e44e33bdcd
    # pid: 16649, system: Linux 2.6.32-220.7.1.el6.x86_64 #1 SMP Fri Feb 10 15:22:22 EST 2012 x86_64
    # exclusive                               : True
    # filename_update                         : None
    # ignore_strand                           : False
    # loglevel                                : 1
    # method                                  : unmerged-combinations
    # output_filename_pattern                 : 030m.intersection.tsv.dir/030m.intersection.tsv-%s.bed.gz
    # output_force                            : True
    # pattern_id                              : (.*).bed.gz
    # stderr                                  : <open file \'<stderr>\', mode \'w\' at 0x2ba70e0c2270>
    # stdin                                   : <open file \'<stdin>\', mode \'r\' at 0x2ba70e0c2150>
    # stdlog                                  : <open file \'030m.intersection.tsv.log\', mode \'a\' at 0x1f1a810>
    # stdout                                  : <open file \'<stdout>\', mode \'w\' at 0x2ba70e0c21e0>
    # timeit_file                             : None
    # timeit_header                           : None
    # timeit_name                             : all
    # tracks                                  : None

The header contains information about:

    * the script name (``beds2beds.py``)
    * the command line options (``--force --exclusive --method=unmerged-combinations --output-filename-pattern=030m.intersection.tsv.dir/030m.intersection.tsv-%s.bed.gz --log=030m.intersection.tsv.log Irf5-030m-R1.bed.gz Rela-030m-R1.bed.gz``)
    * the time when the job was started (``Thu Mar 29 13:06:33 2012``)
    * the location it was executed (``cgat150.anat.ox.ac.uk``)
    * a unique job id (``e1c16e80-03a1-4023-9417-f3e44e33bdcd``)
    * the pid of the job (``16649``)
    * the system specification (``Linux 2.6.32-220.7.1.el6.x86_64 #1 SMP Fri Feb 10 15:22:22 EST 2012 x86_64``)

It is followed by a list of all options that have been set in the script.
    
Once completed, a script will call the :py:func:`Stop` function to signify the end of the experiment.
 
.. autofunction:: Experiment.Stop

:py:func:`Stop` will output to the log file that the script has concluded successfully. Below is typical output::

    # job finished in 11 seconds at Thu Mar 29 13:06:44 2012 -- 11.36  0.45  0.00  0.01 -- e1c16e80-03a1-4023-9417-f3e44e33bdcd

The footer contains information about:

   * the job has finished (``job finished``)
   * the time it took to execute (``11 seconds``)
   * when it completed (``Thu Mar 29 13:06:44 2012``)
   * some benchmarking information (``11.36  0.45  0.00  0.01``) which is 
         ``user time``, ``system time``, ``child user time``, ``child system time``.
   * the unique job id (``e1c16e80-03a1-4023-9417-f3e44e33bdcd``)

The unique job id can be used to easily retrieve matching information from a concatenation of 
log files.

Benchmarking
------------




Complete reference
------------------
'''

import string
import re
import sys
import time
import inspect
import os
import logging
import collections
import types
import subprocess
import gzip

import optparse
import textwrap


class DefaultOptions:
    stdlog = sys.stdout
    stdout = sys.stdout
    stderr = sys.stderr
    stdin = sys.stdin
    loglevel = 2
    timeit_file = None

global_starting_time = time.time()
global_options = DefaultOptions()
global_args = None
# import hashlib
# global_id = hashlib.md5(time.asctime(time.localtime(time.time()))).hexdigest()
import random
import uuid
global_id = uuid.uuid4()
global_benchmark = collections.defaultdict(int)

##########################################################################
# The code for BetterFormatter has been taken from
# http://code.google.com/p/yjl/source/browse/Python/snippet/BetterFormatter.py
__copyright__ = """
Copyright (c) 2001-2006 Gregory P. Ward.  All rights reserved.
Copyright (c) 2002-2006 Python Software Foundation.  All rights reserved.
Copyright (c) 2011 Yu-Jie Lin.  All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

  * Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

  * Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in the
    documentation and/or other materials provided with the distribution.

  * Neither the name of the author nor the names of its
    contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


class BetterFormatter(optparse.IndentedHelpFormatter):

    def __init__(self, *args, **kwargs):

        optparse.IndentedHelpFormatter.__init__(self, *args, **kwargs)
        self.wrapper = textwrap.TextWrapper(width=self.width)

    def _formatter(self, text):

        return '\n'.join(['\n'.join(p) for p in map(self.wrapper.wrap,
                                                    self.parser.expand_prog_name(text).split('\n'))])

    def format_description(self, description):

        if description:
            return self._formatter(description) + '\n'
        else:
            return ''

    def format_epilog(self, epilog):

        if epilog:
            return '\n' + self._formatter(epilog) + '\n'
        else:
            return ''

    def format_usage(self, usage):

        return self._formatter(optparse._("Usage: %s\n") % usage)

    def format_option(self, option):
        # Ripped and modified from Python 2.6's optparse's HelpFormatter
        result = []
        opts = self.option_strings[option]
        opt_width = self.help_position - self.current_indent - 2
        if len(opts) > opt_width:
            opts = "%*s%s\n" % (self.current_indent, "", opts)
            indent_first = self.help_position
        else:                       # start help on same line as opts
            opts = "%*s%-*s  " % (self.current_indent, "", opt_width, opts)
            indent_first = 0
        result.append(opts)
        if option.help:
            help_text = self.expand_default(option)
            # Added expand program name
            help_text = self.parser.expand_prog_name(help_text)
            # Modified the generation of help_line
            help_lines = []
            wrapper = textwrap.TextWrapper(width=self.help_width)
            for p in map(wrapper.wrap, help_text.split('\n')):
                if p:
                    help_lines.extend(p)
                else:
                    help_lines.append('')
            # End of modification
            result.append("%*s%s\n" % (indent_first, "", help_lines[0]))
            result.extend(["%*s%s\n" % (self.help_position, "", line)
                           for line in help_lines[1:]])
        elif opts[-1] != "\n":
            result.append("\n")
        return "".join(result)


# End of BetterFormatter()
#################################################################
#################################################################
#################################################################
class AppendCommaOption(optparse.Option):

    '''Option with additional parsing capabilities.

    * "," in arguments to options that have the action 'append' 
      are treated as a list of options. This is what galaxy does, 
      but generally convenient.

    * Option values of "None" and "" are treated as default values.
    '''
#    def check_value( self, opt, value ):
# do not check type for ',' separated lists
#        if "," in value:
#            return value
#        else:
#            return optparse.Option.check_value( self, opt, value )
#
#    def take_action(self, action, dest, opt, value, values, parser):
#        if action == "append" and "," in value:
#            lvalue = value.split(",")
#            values.ensure_value(dest, []).extend(lvalue)
#        else:
#            optparse.Option.take_action(
#                self, action, dest, opt, value, values, parser)
#

    def convert_value(self, opt, value):
        if value is not None:
            if self.nargs == 1:
                if self.action == "append":
                    if "," in value:
                        return [self.check_value(opt, v) for v in value.split(",") if v != ""]
                    else:
                        if value != "":
                            return self.check_value(opt, value)
                        else:
                            return value
                else:
                    return self.check_value(opt, value)
            else:
                return tuple([self.check_value(opt, v) for v in value])

    # why is it necessary to pass action and dest to this function when
    # they could be accessed as self.action and self.dest?
    def take_action(self, action, dest, opt, value, values, parser):

        if action == "append" and type(value) == list:
            values.ensure_value(dest, []).extend(value)
        else:
            optparse.Option.take_action(
                self, action, dest, opt, value, values, parser)

#################################################################
#################################################################
#################################################################


class OptionParser(optparse.OptionParser):

    '''CGAT derivative of OptionParser.
    '''

    def __init__(self, *args, **kwargs):
        # if "--short" is a command line option
        # remove usage from kwargs
        if "--no-usage" in sys.argv:
            kwargs["usage"] = None

        optparse.OptionParser.__init__(self, *args,
                                       option_class=AppendCommaOption,
                                       formatter=BetterFormatter(),
                                       **kwargs)

        # set new option parser
        # parser.formatter = BetterFormatter()
        # parser.formatter.set_parser(parser)
        if "--no-usage" in sys.argv:
            self.add_option("--no-usage", dest="help_no_usage",
                            action="store_true",
                            help="output help without usage information")


#################################################################
def openFile(filename, mode="r", create_dir=False):
    '''open file in *filename* with mode *mode*.

    If *create* is set, the directory containing filename
    will be created if it does not exist.

    gzip - compressed files are recognized by the
    suffix ``.gz`` and opened transparently.

    Note that there are differences in the file
    like objects returned, for example in the
    ability to seek.

    returns a file or file-like object.
    '''

    _, ext = os.path.splitext(filename)

    if create_dir:
        dirname = os.path.dirname(filename)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname)

    if ext.lower() in (".gz", ".z"):
        return gzip.open(filename, mode)
    else:
        return open(filename, mode)

#################################################################


def getHeader():
    """return a header string with command line options and timestamp

    """
    system, host, release, version, machine = os.uname()
    return "# output generated by %s\n# job started at %s on %s -- %s\n# pid: %i, system: %s %s %s %s" %\
           (" ".join(sys.argv),
            time.asctime(time.localtime(time.time())),
            host,
            global_id,
            os.getpid(),
            system, release, version, machine)


def getParams(options=None):
    """return a string containing script parameters.

    Parameters are all variables that start with ``param_``.
    """
    result = []
    if options:
        members = options.__dict__
        for k, v in sorted(members.items()):
            result.append("# %-40s: %s" % (k, str(v).encode("string_escape")))
    else:
        vars = inspect.currentframe().f_back.f_locals
        for var in filter(lambda x: re.match("param_", x), vars.keys()):
            result.append("# %-40s: %s" %
                          (var, str(vars[var]).encode("string_escape")))

    if result:
        return "\n".join(result)
    else:
        return "# no parameters."


def getFooter():
    """return a header string with command line options and
    timestamp.
    """
    return "# job finished in %i seconds at %s -- %s -- %s" %\
           (time.time() - global_starting_time,
            time.asctime(time.localtime(time.time())),
            " ".join(map(lambda x: "%5.2f" % x, os.times()[:4])),
            global_id)

######################################################################
# Deprecated old call interface


def GetFooter():
    return getFooter()


def GetHeader():
    return getHeader()


def GetParams():
    return getParams()

######################################################################


def Start(parser=None,
          argv=sys.argv,
          quiet=False,
          no_parsing=False,
          add_csv_options=False,
          add_mysql_options=False,
          add_psql_options=False,
          add_pipe_options=True,
          add_cluster_options=False,
          add_output_options=False,
          return_parser=False):
    """set up an experiment.

    *param parser* an :py:class:`E.OptionParser` instance with commandi line options.
    *param argv* command line options to parse. Defaults to :py:data:`sys.argv`
    *quiet* set :term:`loglevel` to 0 - no logging
    *no_parsing* do not parse command line options
    *return_parser* return the parser object, no parsing
    *add_csv_options* add common options for parsing :term:`tsv` separated files
    *add_mysql_options* add common options for connecting to mysql_ databases
    *add_psql_options* add common options for connecting to postgres_ databases
    *add_pipe_options* add common options for redirecting input/output
    *add_cluster_options* add common options for scripts submitting jobs to the cluster
    *add_output_options* add commond options for working with multiple output files
    *returns* a tuple (options,args) with options (a :py:class:`E.OptionParser` object 
        and a list of positional arguments.

    The :py:func:`Start` method will also set up a file logger.

    The default options added by this method are:

    ``-v/--verbose`` 
        the :term:`loglevel`

    ``timeit``
        turn on benchmarking information and save to file

    ``timeit-name``
         name to use for timing information, 

    ``timeit-header``
         output header for timing information.

    ``seed``
         the random seed. If given, the python random 
         number generator will be initialized with this 
         seed.

    Optional options added are:

    add_csv_options

       ``dialect``
            csv_dialect. the default is ``excel-tab``, defaulting to :term:`tsv` formatted files.

    add_psql_options
       ``-C/--connection``
           psql connection string
       ``-U/--user``
           psql user name

    add_cluster_options
       ``--use-cluster``
           use cluster
       ``--cluster-priority``
           cluster priority to request
       ``--cluster-queue``
           cluster queue to use
       ``--cluster-num-jobs``
           number of jobs to submit to the cluster at the same time
       ``--cluster-options``
           additional options to the cluster for each job.

    add_output_options
       ``-P/--output-filename-pattern``
            Pattern to use for output filenames.

    """

    if not parser:
        parser = OptionParser(
            version="%prog version: $Id: Experiment.py 2803 2009-10-22 13:41:24Z andreas $")

    global global_options, global_args, global_starting_time

    global_starting_time = time.time()

    parser.add_option("-v", "--verbose", dest="loglevel", type="int",
                      help="loglevel [%default]. The higher, the more output.")

    parser.add_option("--timeit", dest='timeit_file', type="string",
                      help="store timeing information in file [%default].")
    parser.add_option("--timeit-name", dest='timeit_name', type="string",
                      help="name in timing file for this class of jobs [%default].")
    parser.add_option("--timeit-header", dest='timeit_header', action="store_true",
                      help="add header for timing information [%default].")
    parser.add_option("--random-seed", dest='random_seed', type="int",
                      help="random seed to initialize number generator with [%default].")

    if quiet:
        parser.set_defaults(loglevel=0)
    else:
        parser.set_defaults(loglevel=1)

    parser.set_defaults(
        timeit_file=None,
        timeit_name='all',
        timeit_header=None,
        random_seed=None,
    )

    if add_csv_options:
        parser.add_option("--dialect", dest="csv_dialect", type="string",
                          help="csv dialect to use [%default].")

        parser.set_defaults(
            csv_dialect="excel-tab",
            csv_lineterminator="\n",
        )

    if add_psql_options:
        parser.add_option("-C", "--connection", dest="psql_connection", type="string",
                          help="psql connection string [%default].")
        parser.add_option("-U", "--user", dest="user", type="string",
                          help="database user name [%default].")

        parser.set_defaults(psql_connection="fgu202:postgres")
        parser.set_defaults(user="")

    if add_cluster_options:
        parser.add_option("--use-cluster", dest="use_cluster", action="store_true",
                          help="use cluster [%default].")
        parser.add_option("--cluster-priority", dest="cluster_priority", type="int",
                          help="set job priority on cluster [%default].")
        parser.add_option("--cluster-queue", dest="cluster_queue", type="string",
                          help="set cluster queue [%default].")
        parser.add_option("--cluster-num-jobs", dest="cluster_num_jobs", type="int",
                          help="number of jobs to submit to the queue execute in parallel [%default].")
        parser.add_option("--cluster-options", dest="cluster_options", type="string",
                          help="additional options for cluster jobs, passed on to qrsh [%default].")

        parser.set_defaults(use_cluster=False,
                            cluster_queue="all.q",
                            cluster_priority=-10,
                            cluster_num_jobs=100,
                            cluster_options="")

    if add_output_options:
        parser.add_option("-P", "--output-filename-pattern", dest="output_filename_pattern", type="string",
                          help="OUTPUT filename pattern for various methods [%default].")

        parser.add_option("-F", "--force", dest="output_force", action="store_true",
                          help="force over-writing of existing files.")

        parser.set_defaults(output_filename_pattern="%s",
                            output_force=False)

    if add_pipe_options:
        parser.add_option("-I", "--stdin", dest="stdin", type="string",
                          help="file to read stdin from [default = stdin].",
                          metavar="FILE")
        parser.add_option("-L", "--log", dest="stdlog", type="string",
                          help="file with logging information [default = stdout].",
                          metavar="FILE")
        parser.add_option("-E", "--error", dest="stderr", type="string",
                          help="file with error information [default = stderr].",
                          metavar="FILE")
        parser.add_option("-S", "--stdout", dest="stdout", type="string",
                          help="file where output is to go [default = stdout].",
                          metavar="FILE")

        parser.set_defaults(stderr=sys.stderr)
        parser.set_defaults(stdout=sys.stdout)
        parser.set_defaults(stdlog=sys.stdout)
        parser.set_defaults(stdin=sys.stdin)

    if add_mysql_options:
        parser.add_option("-H", "--host", dest="host", type="string",
                          help="mysql host [%default].")
        parser.add_option("-D", "--database", dest="database", type="string",
                          help="mysql database [%default].")
        parser.add_option("-U", "--user", dest="user", type="string",
                          help="mysql username [%default].")
        parser.add_option("-P", "--password", dest="password", type="string",
                          help="mysql password [%default].")
        parser.add_option("-O", "--port", dest="port", type="int",
                          help="mysql port [%default].")

        parser.set_defaults(host="db",
                            port=3306,
                            user="",
                            password="",
                            database="")

    if return_parser:
        return parser

    if not no_parsing:
        (global_options, global_args) = parser.parse_args(argv[1:])

    if global_options.random_seed is not None:
        random.seed(global_options.random_seed)

    if add_pipe_options:
        if global_options.stdout != sys.stdout:
            global_options.stdout = openFile(global_options.stdout, "w")
        if global_options.stderr != sys.stderr:
            if global_options.stderr == "stderr":
                global_options.stderr = global_options.stderr
            else:
                global_options.stderr = openFile(global_options.stderr, "w")
        if global_options.stdlog != sys.stdout:
            global_options.stdlog = openFile(global_options.stdlog, "a")
        if global_options.stdin != sys.stdin:
            global_options.stdin = openFile(global_options.stdin, "r")
    else:
        global_options.stderr = sys.stderr
        global_options.stdout = sys.stdout
        global_options.stdlog = sys.stdout
        global_options.stdin = sys.stdin

    if global_options.loglevel >= 1:
        global_options.stdlog.write(getHeader() + "\n")
        global_options.stdlog.write(getParams(global_options) + "\n")
        global_options.stdlog.flush()

    # configure logging
    # map from 0-10 to logging scale
    # 0: quiet
    # 1: little verbositiy
    # >1: increased verbosity
    if global_options.loglevel == 0:
        lvl = logging.ERROR
    elif global_options.loglevel == 1:
        lvl = logging.INFO
    else:
        lvl = logging.DEBUG

    if global_options.stdout == global_options.stdlog:
        logging.basicConfig(
            level=lvl,
            format='# %(asctime)s %(levelname)s %(message)s',
            stream=global_options.stdlog)
    else:
        logging.basicConfig(
            level=lvl,
            format='%(asctime)s %(levelname)s %(message)s',
            stream=global_options.stdlog)

    return global_options, global_args


def Stop():
    """stop the experiment."""

    if global_options.loglevel >= 1 and global_benchmark:
        t = time.time() - global_starting_time
        global_options.stdlog.write(
            "######### Time spent in benchmarked functions ###################\n")
        global_options.stdlog.write("# function\tseconds\tpercent\n")
        for key, value in global_benchmark.items():
            global_options.stdlog.write(
                "# %s\t%6i\t%5.2f%%\n" % (key, value, (100.0 * float(value) / t)))
        global_options.stdlog.write(
            "#################################################################\n")

    if global_options.loglevel >= 1:
        global_options.stdlog.write(getFooter() + "\n")

    # close files
    if global_options.stdout != sys.stdout:
        global_options.stdout.close()
    # do not close log, otherwise the following error occurs:
    # Error in sys.exitfunc:
    # Traceback (most recent call last):
    #   File "/net/cpp-group/server/lib/python2.6/atexit.py", line 24, in _run_exitfuncs
    #     func(*targs, **kargs)
    #   File "/net/cpp-group/server/lib/python2.6/logging/__init__.py", line 1472, in shutdown
    #     h.flush()
    #   File "/net/cpp-group/server/lib/python2.6/logging/__init__.py", line 740, in flush
    #     self.stream.flush()
    # ValueError: I/O operation on closed file
    # if global_options.stdlog != sys.stdout: global_options.stdlog.close()
    if global_options.stderr != sys.stderr:
        global_options.stderr.close()

    if global_options.timeit_file:

        outfile = open(global_options.timeit_file, "a")

        if global_options.timeit_header:
            outfile.write("\t".join(("name", "wall", "user", "sys", "cuser", "csys",
                                     "host", "system", "release", "machine",
                                     "start", "end", "path", "cmd")) + "\n")

        csystem, host, release, version, machine = map(str, os.uname())
        uusr, usys, c_usr, c_sys = map(lambda x: "%5.2f" % x, os.times()[:4])
        t_end = time.time()
        c_wall = "%5.2f" % (t_end - global_starting_time)

        if sys.argv[0] == "run.py":
            cmd = global_args[0]
            if len(global_args) > 1:
                cmd += " '" + "' '".join(global_args[1:]) + "'"
        else:
            cmd = sys.argv[0]

        result = "\t".join((global_options.timeit_name,
                            c_wall, uusr, usys, c_usr, c_sys,
                            host, csystem, release, machine,
                            time.asctime(time.localtime(global_starting_time)),
                            time.asctime(time.localtime(t_end)),
                            os.path.abspath(os.getcwd()),
                            cmd)) + "\n"

        outfile.write(result)
        outfile.close()


def benchmark(func):
    """decorator collecting wall clock time spent in decorated method."""

    def wrapper(*arg):
        t1 = time.time()
        res = func(*arg)
        t2 = time.time()
        key = "%s:%i" % (func.func_name, func.func_code.co_firstlineno)
        global_benchmark[key] += t2 - t1
        global_options.stdlog.write(
            '## benchmark: %s completed in %6.4f s\n' % (key, (t2 - t1)))
        global_options.stdlog.flush()
        return res
    return wrapper

# there are differences whether you cache a function or
# an objects method


def cachedmethod(function):
    '''decorator for caching a method.'''
    return Memoize(function)


class cachedfunction(object):

    """Decorator that caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated.

    Taken from http://wiki.python.org/moin/PythonDecoratorLibrary#Memoize
    """

    def __init__(self, func):
        self.func = func
        self.cache = {}

    def __call__(self, *args):
        try:
            return self.cache[args]
        except KeyError:
            value = self.func(*args)
            self.cache[args] = value
            return value
        except TypeError:
            # uncachable -- for instance, passing a list as an argument.
            # Better to not cache than to blow up entirely.
            return self.func(*args)

    def __repr__(self):
        """Return the function's docstring."""
        return self.func.__doc__

    def __get__(self, obj, objtype):
        """Support instance methods."""
        return functools.partial(self.__call__, obj)


class Memoize(object):

    def __init__(self, fn):
        self.cache = {}
        self.fn = fn

    def __get__(self, instance, cls=None):
        self.instance = instance
        return self

    def __call__(self, *args):
        if self.cache.has_key(args):
            return self.cache[args]
        else:
            object = self.cache[args] = self.fn(self.instance, *args)
            return object


def log(loglevel, message):
    """log message at loglevel."""
    logging.log(loglevel, message)


def info(message):
    '''log information message, see the :mod:`logging` module'''
    logging.info(message)


def warning(message):
    '''log warning message, see the :mod:`logging` module'''
    logging.warning(message)


def warn(message):
    '''log warning message, see the :mod:`logging` module'''
    logging.warning(message)


def debug(message):
    '''log debugging message, see the :mod:`logging` module'''
    logging.debug(message)


def error(message):
    '''log error message, see the :mod:`logging` module'''
    logging.error(message)


def critical(message):
    '''log critical message, see the :mod:`logging` module'''
    logging.critical(message)


def getOutputFile(section):
    '''return filename to write to.'''
    return re.sub("%s", section, global_options.output_filename_pattern)


def openOutputFile(section, mode="w"):
    """open file for writing substituting section in the
    output_pattern (if defined).

    If the filename ends with ".gz", the output is opened
    as a gzip'ed file.
    """

    fn = getOutputFile(section)
    try:
        if fn == "-":
            return global_options.stdout
        else:
            if not global_options.output_force and os.path.exists(fn):
                raise OSError(
                    ("file %s already exists, use --force to "
                     "overwrite existing files.") % fn)
            if fn.endswith(".gz"):
                return gzip.open(fn, mode)
            else:
                return open(fn, mode)
    except AttributeError:
        return global_options.stdout


class Counter(object):

    '''a counter class.

    The counter acts both as a dictionary and
    a object permitting attribute access.

    Counts are automatically initialized to 0.

    Instantiate and use like this::

       c = Counter()
       c.input += 1
       c.output += 2
       c["skipped"] += 1

       print str(c)
    '''

    __slots__ = ["_counts"]

    def __init__(self):
        """Store data returned by function."""
        object.__setattr__(self, "_counts", collections.defaultdict(int))

    def __setitem__(self, key, value):
        self._counts[key] = value

    def __getitem__(self, key):
        return self._counts[key]

    def __getattr__(self, name):
        return self._counts[name]

    def __setattr__(self, name, value):
        self._counts[name] = value

    def __str__(self):
        return ", ".join("%s=%i" % x for x in self._counts.iteritems())

    def __iadd__(self, other):
        try:
            for key, val in other.iteritems():
                self._counts[key] += val
        except:
            raise TypeError("unknown type")
        return self

    def iteritems(self):
        return self._counts.iteritems()

    def asTable(self):
        '''return values as tab-separated table (without header).'''
        return '\n'.join("%s\t%i" % x for x in self._counts.iteritems())


class Experiment:

    mShortOptions = ""
    mLongOptions = []

    mLogLevel = 0
    mTest = 0
    mDatabaseName = None

    mName = sys.argv[0]

    def __init__(self):

        # process command-line arguments
        (self.mOptlist, self.mArgs) = self.ParseCommandLine()

        # set options now
        self.ProcessOptions(self.mOptlist)

    def DumpParameters(self):
        """dump parameters of this object. All parameters start with a lower-case m."""

        members = self.__dict__

        print "#--------------------------------------------------------------------------------------------"
        print "#" + string.join(sys.argv)
        print "# pid: %i, system:" % os.getpid(), string.join(os.uname(), ",")
        print "#--------------------------------------------------------------------------------------------"
        print "# Parameters for instance of <" + self.mName + "> on " + time.asctime(time.localtime(time.time()))

        member_keys = list(members.keys())
        member_keys.sort()
        for member in member_keys:
            if member[0] == 'm':
                print "# %-40s:" % member, members[member]

        print "#--------------------------------------------------------------------------------------------"
        sys.stdout.flush()

    #-----------------------------> Control functions <-----------------------

    # ------------------------------------------------------------------------
    def ProcessOptions(self, optlist):
        """Sets options in this module. Please overload as necessary."""

        for o, a in optlist:
            if o in ("-V", "--Verbose"):
                self.mLogLevel = string.atoi(a)
            elif o in ("-T", "--test"):
                self.mTest = 1

    # ------------------------------------------------------------------------
    def ProcessArguments(self, args):
        """Perform actions as given in command line arguments."""

        if self.mLogLevel >= 1:
            self.DumpParameters()

        for arg in args:
            if arg[-1] == ")":
                statement = "self.%s" % arg
            else:
                statement = "self.%s()" % arg
            exec statement

            if self.mLogLevel >= 1:
                print "--------------------------------------------------------------------------------------------"
                print statement + " finished at " + time.asctime(time.localtime(time.time()))
                print "--------------------------------------------------------------------------------------------"

    # ------------------------------------------------------------------------
    def ParseCommandLine(self):
        """Call subroutine with command line arguments."""

        self.mShortOptions = self.mShortOptions + "V:D:T"
        self.mLongOptions.append("Verbose=")
        self.mLongOptions.append("Database=")
        self.mLongOptions.append("Test")

        try:
            optlist, args = getopt.getopt(sys.argv[1:],
                                          self.mShortOptions,
                                          self.mLongOptions)
        except getopt.error, msg:
            self.PrintUsage()
            print msg
            sys.exit(2)

        return optlist, args

    #-------------------------------------------------------------------------
    def Process(self):
        self.ProcessArguments(self.mArgs)

    #-------------------------------------------------------------------------
    def PrintUsage(self):
        """print usage information."""

        print "# valid short options are:", self.mShortOptions
        print "# valid long options are:", str(self.mLongOptions)


def run(cmd, return_stdout=False, **kwargs):
    '''executed a command line cmd.

    returns the return code.

    If *return_stdout* is True, the contents of stdout
    are returned.

    ``kwargs`` are passed on to subprocess.call or subprocess.check_output.

    raises OSError if process failed or was terminated.
    '''

    # remove new lines
    cmd = " ".join(re.sub("\t+", " ", cmd).split("\n")).strip()

    if "<(" in cmd:
        if "'" in cmd:
            raise ValueError(
                "advanced bash syntax combined with single quotes")
        cmd = """/bin/bash -c '%s'""" % cmd

    if return_stdout:
        return subprocess.check_output(cmd, shell=True, **kwargs)
    else:
        retcode = subprocess.call(cmd, shell=True, **kwargs)
        if retcode < 0:
            raise OSError("process was terminated by signal %i" % -retcode)
        return retcode
