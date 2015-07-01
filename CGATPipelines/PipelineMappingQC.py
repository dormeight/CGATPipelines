"""
======================================================
PipelineMappingQC.py - common tasks for QC'ing mapping
======================================================

:Author: Andreas Heger
:Release: $Id$
:Date: |today|
:Tags: Python

Purpose
-------


Usage
-----

Type::

   python <script_name>.py --help

for command line help.

Code
----


"""

import CGAT.Experiment as E
import os
import re
import CGAT.IOTools as IOTools
import CGATPipelines.Pipeline as P


def getPicardOptions():
    return "-l mem_free=1.4G"


def getNumReadsFromReadsFile(infile):
    '''get number of reads from a .nreads file.'''
    with IOTools.openFile(infile) as inf:
        line = inf.readline()
        if not line.startswith("nreads"):
            raise ValueError(
                "parsing error in file '%s': "
                "expected first line to start with 'nreads'")
        nreads = int(line[:-1].split("\t")[1])
    return nreads


def getNumReadsFromBAMFile(infile):
    '''count number of reads in bam file.'''
    # by-passes a problem with pysam, which was reading in stdout as the first
    # elements in list data
    tmpf = P.getTempFile(".")
    tmpfile_name = tmpf.name
    statement = '''samtools idxstats %(infile)s > %(tmpfile_name)s'''

    P.run()

    read_info = IOTools.openFile(tmpfile_name).readlines()
    os.unlink(tmpfile_name)

    try:
        data = sum(map(int, [x.split("\t")[2]
                   for x in read_info if not x.startswith("#")]))

    except IndexError, msg:
        raise IndexError(
            "can't get number of reads from bamfile, msg=%s, data=%s" %
            (msg, read_info))
    return data


def buildPicardInsertSizeStats(infile, outfile, genome_file):
    '''gather BAM file insert size statistics using Picard '''

    job_options = getPicardOptions()
    job_threads = 3

    if getNumReadsFromBAMFile(infile) == 0:
        E.warn("no reads in %s - no metrics" % infile)
        P.touch(outfile)
        return

    statement = '''CollectInsertSizeMetrics
    INPUT=%(infile)s
    REFERENCE_SEQUENCE=%(genome_file)s
    ASSUME_SORTED=true
    OUTPUT=%(outfile)s
    VALIDATION_STRINGENCY=SILENT
    >& %(outfile)s'''

    P.run()


def buildPicardAlignmentStats(infile, outfile, genome_file):
    '''gather BAM file alignment statistics using Picard '''

    job_options = getPicardOptions()
    job_threads = 3

    if getNumReadsFromBAMFile(infile) == 0:
        E.warn("no reads in %s - no metrics" % infile)
        P.touch(outfile)
        return

    # Picard seems to have problem if quality information is missing
    # or there is no sequence/quality information within the bam file.
    # Thus, add it explicitly.
    statement = '''cat %(infile)s
    | python %(scriptsdir)s/bam2bam.py -v 0
    --method=set-sequence --output-sam
    | CollectMultipleMetrics
    INPUT=/dev/stdin
    REFERENCE_SEQUENCE=%(genome_file)s
    ASSUME_SORTED=true
    OUTPUT=%(outfile)s
    VALIDATION_STRINGENCY=SILENT
    >& %(outfile)s'''

    P.run()


def buildPicardDuplicationStats(infile, outfile):
    '''Record duplicate metrics using Picard, the marked records
    are discarded
    '''

    job_options = getPicardOptions()
    job_threads = 3

    if getNumReadsFromBAMFile(infile) == 0:
        E.warn("no reads in %s - no metrics" % infile)
        P.touch(outfile)
        return

    # currently, MarkDuplicates cannot handle split alignments from gsnap
    # these can be identified by the custom XT tag.
    if ".gsnap.bam" in infile:
        tmpf = P.getTempFile(".")
        tmpfile_name = tmpf.name
        statement = '''samtools view -h %(infile)s
        | awk "!/\\tXT:/"
        | samtools view /dev/stdin -S -b > %(tmpfile_name)s;
        ''' % locals()
        data_source = tmpfile_name
    else:
        statement = ""
        data_source = infile

    statement += '''MarkDuplicates
    INPUT=%(data_source)s
    ASSUME_SORTED=true
    METRICS_FILE=%(outfile)s
    OUTPUT=/dev/null
    VALIDATION_STRINGENCY=SILENT
    '''

    P.run()

    if ".gsnap.bam" in infile:
        os.unlink(tmpfile_name)


def buildPicardDuplicateStats(infile, outfile):
    '''Record duplicate metrics using Picard and keep the dedupped .bam file'''

    job_options = getPicardOptions()
    job_threads = 3

    if getNumReadsFromBAMFile(infile) == 0:
        E.warn("no reads in %s - no metrics" % infile)
        P.touch(outfile)
        return

    statement = '''MarkDuplicates
    INPUT=%(infile)s
    ASSUME_SORTED=true
    METRICS_FILE=%(outfile)s.duplicate_metrics
    OUTPUT=%(outfile)s
    VALIDATION_STRINGENCY=SILENT ;
    '''
    statement += '''samtools index %(outfile)s ;'''
    P.run()


def buildPicardCoverageStats(infile, outfile, baits, regions):
    '''Generate coverage statistics for regions of interest from a bed
    file using Picard'''
    job_options = getPicardOptions()
    job_threads = 3

    if getNumReadsFromBAMFile(infile) == 0:
        E.warn("no reads in %s - no metrics" % infile)
        P.touch(outfile)
        return

    statement = '''CalculateHsMetrics BAIT_INTERVALS=%(baits)s
    TARGET_INTERVALS=%(regions)s
    INPUT=%(infile)s
    OUTPUT=%(outfile)s
    VALIDATION_STRINGENCY=LENIENT''' % locals()
    P.run()


def buildPicardGCStats(infile, outfile, genome_file):
    '''Gather BAM file GC bias stats using Picard '''

    job_options = getPicardOptions()
    job_threads = 3

    if getNumReadsFromBAMFile(infile) == 0:
        E.warn("no reads in %s - no metrics" % infile)
        P.touch(outfile)
        return

    statement = '''CollectGcBiasMetrics
    INPUT=%(infile)s
    REFERENCE_SEQUENCE=%(genome_file)s
    OUTPUT=%(outfile)s
    VALIDATION_STRINGENCY=SILENT
    CHART_OUTPUT=%(outfile)s.pdf
    SUMMARY_OUTPUT=%(outfile)s.summary
    >& %(outfile)s'''

    P.run()


def loadPicardMetrics(infiles, outfile, suffix,
                      pipeline_suffix=".picard_stats",
                      tablename=False):
    '''load picard metrics.'''

    if not tablename:
        tablename = "%s_%s" % (P.toTable(outfile), suffix)

    outf = P.getTempFile(".")

    filenames = ["%s.%s" % (x, suffix) for x in infiles]

    first = True

    for filename in filenames:
        track = P.snip(os.path.basename(filename), "%s.%s" %
                       (pipeline_suffix, suffix))

        if not os.path.exists(filename):
            E.warn("File %s missing" % filename)
            continue

        lines = IOTools.openFile(filename, "r").readlines()

        # extract metrics part
        rx_start = re.compile("## METRICS CLASS")
        for n, line in enumerate(lines):
            if rx_start.search(line):
                lines = lines[n + 1:]
                break

        for n, line in enumerate(lines):
            if not line.strip():
                lines = lines[:n]
                break

        if len(lines) == 0:
            E.warn("no lines in %s: %s" % (track, filename))
            continue
        if first:
            outf.write("%s\t%s" % ("track", lines[0]))
            fields = lines[0][:-1].split("\t")
        else:
            f = lines[0][:-1].split("\t")
            if f != fields:
                raise ValueError(
                    "file %s has different fields: expected %s, got %s" %
                    (filename, fields, f))

        first = False
        for i in range(1, len(lines)):
            outf.write("%s\t%s" % (track, lines[i]))

    outf.close()

    P.load(outf.name,
           outfile,
           options="--add-index=track --allow-empty-file")

    os.unlink(outf.name)


def loadPicardHistogram(infiles, outfile, suffix, column,
                        pipeline_suffix=".picard_stats", tablename=False):
    '''extract a histogram from a picard output file and load
    it into database.'''

    if not tablename:
        tablename = "%s_%s" % (P.toTable(outfile), suffix)
        tablename = tablename.replace("_metrics", "_histogram")

    # some files might be missing
    xfiles = [x for x in infiles if os.path.exists("%s.%s" % (x, suffix))]

    if len(xfiles) == 0:
        E.warn("no files for %s" % tablename)
        return

    header = ",".join([P.snip(os.path.basename(x), pipeline_suffix)
                      for x in xfiles])
    filenames = " ".join(["%s.%s" % (x, suffix) for x in xfiles])

    # there might be a variable number of columns in the tables
    # only take the first ignoring the rest

    load_statement = P.build_load_statement(
        tablename,
        options="--add-index=track "
        " --header-names=%s,%s"
        " --allow-empty-file"
        " --replace-header" % (column, header))

    statement = """python %(scriptsdir)s/combine_tables.py
    --regex-start="## HISTOGRAM"
    --missing-value=0
    --take=2
    %(filenames)s
    | %(load_statement)s
    >> %(outfile)s
    """

    P.run()


def loadPicardAlignmentStats(infiles, outfile):
    '''load all output from Picard's CollectMultipleMetrics
    into sql database.'''

    loadPicardMetrics(infiles, outfile, "alignment_summary_metrics")

    # insert size metrics only available for paired-ended data
    loadPicardMetrics(infiles, outfile, "insert_size_metrics")

    histograms = (("quality_by_cycle_metrics", "cycle"),
                  ("quality_distribution_metrics", "quality"),
                  ("insert_size_metrics", "insert_size"))

    for suffix, column in histograms:
        loadPicardHistogram(infiles, outfile, suffix, column)


def loadPicardDuplicationStats(infiles, outfiles):
    '''load picard duplicate filtering stats.'''
    # SNS: added to enable naming consistency

    outfile_metrics, outfile_histogram = outfiles

    suffix = "picard_duplication_metrics"

    # the loading functions expect "infile_name.pipeline_suffix" as the infile
    # names.
    infile_names = [x[:-len("." + suffix)] for x in infiles]

    loadPicardMetrics(infile_names, outfile_metrics, suffix, "",
                      tablename="picard_duplication_metrics")

    infiles_with_histograms = []

    # The complexity histogram is only present for PE data, so we must check
    # because by design the pipeline does not track endedness
    for infile in infile_names:
        with_hist = False
        with open(".".join([infile, suffix]), "r") as open_infile:
            for line in open_infile:
                if line.startswith("## HISTOGRAM"):
                    infiles_with_histograms.append(infile)
                    break

    if len(infiles_with_histograms) > 0:
        loadPicardHistogram(infiles_with_histograms,
                            outfile_histogram,
                            suffix,
                            "coverage_multiple",
                            "",
                            tablename="picard_complexity_histogram")
    else:
        with open(outfile_histogram, "w") as ofh:
            ofh.write("No histograms detected, no data loaded.")


def loadPicardDuplicateStats(infiles, outfile, pipeline_suffix=".bam"):
    '''load picard duplicate filtering stats.'''

    loadPicardMetrics(
        infiles, outfile, "duplicate_metrics", pipeline_suffix=pipeline_suffix)
    loadPicardHistogram(infiles, outfile, "duplicate_metrics",
                        "duplicates", pipeline_suffix=pipeline_suffix)


def loadPicardCoverageStats(infiles, outfile):
    '''Import coverage statistics into SQLite'''

    outf = P.getTempFile(".")
    first = True
    for f in infiles:
        track = P.snip(os.path.basename(f), ".cov")
        lines = [x for x in open(f, "r").readlines()
                 if not x.startswith("#") and x.strip()]
        if first:
            outf.write("%s\t%s" % ("track", lines[0]))
        first = False
        outf.write("%s\t%s" % (track, lines[1]))
    outf.close()
    P.load(outf.name,
           outfile,
           options="--ignore-empty --add-index=track")
    os.unlink(outf.name)


def buildBAMStats(infile, outfile):
    '''Count number of reads mapped, duplicates, etc. '''

    statement = '''python %(scriptsdir)s/bam2stats.py
    --force-output
    --output-filename-pattern=%(outfile)s.%%s
    < %(infile)s
    > %(outfile)s'''
    P.run()


def loadBAMStats(infiles, outfile):
    '''load bam2stats.py output into sqlite database.'''

    header = ",".join([P.snip(os.path.basename(x), ".readstats")
                      for x in infiles])
    filenames = " ".join(["<( cut -f 1,2 < %s)" % x for x in infiles])

    tablename = P.toTable(outfile)

    load_statement = P.build_load_statement(
        tablename,
        options="--add-index=track "
        " --allow-empty-file")

    E.info("loading bam stats - summary")
    statement = """python %(scriptsdir)s/combine_tables.py
    --header-names=%(header)s
    --missing-value=0
    --ignore-empty
    %(filenames)s
    | perl -p -e "s/bin/track/"
    | python %(scriptsdir)s/table2table.py --transpose
    | %(load_statement)s
    > %(outfile)s"""
    P.run()

    for suffix in ("nm", "nh"):
        E.info("loading bam stats - %s" % suffix)
        filenames = " ".join(["%s.%s" % (x, suffix) for x in infiles])
        
        tablename = "%s_%s" % (P.toTable(outfile), suffix)

        load_statement = P.build_load_statement(
            "%s_%s" % (tablename, suffix),
            options="--allow-empty-file")

        statement = """python %(scriptsdir)s/combine_tables.py
        --header-names=%(header)s
        --skip-titles
        --missing-value=0
        --ignore-empty
        %(filenames)s
        | perl -p -e "s/bin/%(suffix)s/"
        | %(load_statement)s
        >> %(outfile)s """
        P.run()

    # load mapping qualities, there are two columns per row
    # 'all_reads' and 'filtered_reads'
    # Here, only filtered_reads are used (--take=3)
    for suffix in ("mapq",):
        E.info("loading bam stats - %s" % suffix)
        filenames = " ".join(["%s.%s" % (x, suffix) for x in infiles])

        load_statement = P.build_load_statement(
            "%s_%s" % (tablename, suffix),
            options=" --allow-empty-file")

        statement = """python %(scriptsdir)s/combine_tables.py
        --header-names=%(header)s
        --skip-titles
        --missing-value=0
        --ignore-empty
        --take=3
        %(filenames)s
        | perl -p -e "s/bin/%(suffix)s/"
        | %(load_statement)s
        >> %(outfile)s """
        P.run()
