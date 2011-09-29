################################################################################
#
#   MRC FGU Computational Genomics Group
#
#   $Id$
#
#   Copyright (C) 2009 Tildon Grant Belgard
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
#################################################################################
"""
====================
readqc pipeline
====================

:Author: David Sims
:Release: $Id$
:Date: |today|
:Tags: Python

The exome pipeline imports unmapped reads from one or more 
fastq or sra files and aligns them to the genome, then filters calls variants (SNVs and indels) 
and filters them by both depth/rate and regions of interest.

   1. Align to genome using gapped alignment (BWA)
   2. Calculate alignment and coverage statistics (BAMStats)
   3. Call SNVs & indels (SAMtools)
   4. Filter variants (SAMtools / BEDTools)
   5. Calculate variant statistics (vcf-tools)
   6. Produce report (SphinxReport)

Usage
=====

See :ref:`PipelineSettingUp` and :ref:`PipelineRunning` on general information how to use CGAT pipelines.

Configuration
-------------

Input
-----

Reads are imported by placing files or linking to files in the :term:`working directory`.

The default file format assumes the following convention:

   <sample>-<condition>-<replicate>.<suffix>

``sample`` and ``condition`` make up an :term:`experiment`, while ``replicate`` denotes
the :term:`replicate` within an :term:`experiment`. The ``suffix`` determines the file type.
The following suffixes/file types are possible:

sra
   Short-Read Archive format. Reads will be extracted using the :file:`fastq-dump` tool.

fastq.gz
   Single-end reads in fastq format.

fastq.1.gz, fastq2.2.gz
   Paired-end reads in fastq format. The two fastq files must be sorted by read-pair.

.. note::

   Quality scores need to be of the same scale for all input files. Thus it might be
   difficult to mix different formats.



Requirements
------------

On top of the default CGAT setup, the pipeline requires the following software to be in the 
path:

+--------------------+-------------------+------------------------------------------------+
|*Program*           |*Version*          |*Purpose*                                       |
+--------------------+-------------------+------------------------------------------------+
|Stampy              |>=0.9.0            |read mapping                                    |
+--------------------+-------------------+------------------------------------------------+
|BWA                 |                   |read mapping                                    |
+--------------------+-------------------+------------------------------------------------+
|SAMtools            |                   |filtering, SNV / indel calling                  |
+--------------------+-------------------+------------------------------------------------+
|BEDTools            |                   |filtering, SNV / indel calling                  |
+--------------------+-------------------+------------------------------------------------+
|sra-tools           |                   |extracting reads from .sra files                |
+--------------------+-------------------+------------------------------------------------+
|picard              |>=1.38             |bam/sam files. The .jar files need to be in your|
|                    |                   | CLASSPATH environment variable.                |
+--------------------+-------------------+------------------------------------------------+
|vcf-tools           |                   |                                                |
+--------------------+-------------------+------------------------------------------------+
|BAMStats            |                   |                                                |
+--------------------+-------------------+------------------------------------------------+

Pipeline output
===============

The major output is a single VCF file and an HTML quality control report.

Example
=======

ToDo: make exome sequencing example


Code
====

"""

# load modules
from ruffus import *
from rpy2.robjects import r as R

import Experiment as E
import logging as L
import Database
import sys, os, re, shutil, itertools, math, glob, time, gzip, collections, random
import numpy, sqlite3
import GTF, IOTools, IndexedFasta
import Tophat
import rpy2.robjects as ro
import PipelineGeneset
import PipelineMapping
import Stats
import PipelineTracks
import Pipeline as P

USECLUSTER = True

#########################################################################
#########################################################################
#########################################################################
# load options from the config file
P.getParameters( ["%s.ini" % __file__[:-len(".py")], "../exome.ini", "exome.ini" ] )
PARAMS = P.PARAMS

#########################################################################
#########################################################################
#########################################################################
@files( PARAMS["roi_bed"], "roi.load" )
def loadROI( infiles, outfile ):
    '''Import regions of interest bed file into SQLite.'''
    scriptsdir = PARAMS["general_scriptsdir"]
    header = "chr,start,stop,feature"
    tablename = P.toTable( outfile )
    E.info( "loading regions of interest" )
    statement = '''cat %(infiles)s
            | python %(scriptsdir)s/csv2db.py %(csv2db_options)s
              --allow-empty
              --header=%(header)s
              --index=feature
              --table=%(tablename)s 
            > %(outfile)s  '''      
    P.run()

#########################################################################
#########################################################################
#########################################################################
@files( PARAMS["roi_to_gene"], "roi2gene.load" )
def loadROI2Gene( infiles, outfile ):
    '''Import genes mapping to regions of interest bed file into SQLite.'''

    scriptsdir = PARAMS["general_scriptsdir"]
    tablename = P.toTable( outfile )
    E.info( "loading roi to gene mapping" )
    statement = '''cat %(infiles)s
            | python %(scriptsdir)s/csv2db.py %(csv2db_options)s
              --allow-empty
              --index=feature
              --index=gene_symbol
              --table=%(tablename)s 
            > %(outfile)s  '''      
    P.run()

#########################################################################
#########################################################################
#########################################################################
@files( PARAMS["samples"], "samples.load" )
def loadSamples( infiles, outfile ):
    '''Import sample information into SQLite.'''

    scriptsdir = PARAMS["general_scriptsdir"]
    tablename = P.toTable( outfile )
    E.info( "loading samples" )
    statement = '''cat %(infiles)s
            | python %(scriptsdir)s/csv2db.py %(csv2db_options)s
              --allow-empty
              --index=track
              --index=category
              --table=%(tablename)s 
            > %(outfile)s  '''      
    P.run()

#########################################################################
#########################################################################
#########################################################################
@transform( ("*.fastq.1.gz", 
             "*.fastq.gz",
             "*.sra"),
             regex( r"(\S+).(fastq.1.gz|fastq.gz|sra)"),
             r"\1/bam/\1.bam")
def mapReads(infiles, outfile):
    '''Map reads to the genome using BWA '''
    to_cluster = USECLUSTER
    track = P.snip( os.path.basename(outfile), ".bam" )
    try: os.mkdir( track )
    except OSError: pass
    try: os.mkdir( '''%(track)s/bam''' % locals() )
    except OSError: pass
    m = PipelineMapping.bwa()
    statement = m.build((infiles,), outfile) 
    P.run()

#########################################################################
#########################################################################
#########################################################################
@transform( mapReads,
            regex( r"(\S+)/bam/(\S+).bam"),
            r"\1/bam/\2.dedup.bam")
def dedup(infiles, outfile):
        '''Remove duplicate alignments from BAM files.'''
        to_cluster = USECLUSTER
        track = P.snip( outfile, ".bam" )
        dedup_method = PARAMS["dedup_method"]
        if dedup_method == 'samtools':
            statement = '''samtools rmdup %(infiles)s %(outfile)s; ''' % locals()    
        elif dedup_method == 'picard':
            statement = '''MarkDuplicates INPUT=%(infiles)s  ASSUME_SORTED=true OUTPUT=%(outfile)s METRICS_FILE=%(track)s.dupstats VALIDATION_STRINGENCY=SILENT; ''' % locals()
        statement += '''samtools index %(outfile)s; ''' % locals()
        #print statement
        P.run()

#########################################################################
#########################################################################
#########################################################################
@merge( dedup, "picard_duplicate_stats.load" )
def loadPicardDuplicateStats( infiles, outfile ):
    '''Merge Picard duplicate stats into single table and load into SQLite.'''

    tablename = P.toTable( outfile )

    outf = open('dupstats.txt','w')

    first = True
    for f in infiles:
        track = P.snip( os.path.basename(f), ".dedup.bam" )
        statfile = P.snip(f, ".bam" )  + ".dupstats"
        if not os.path.exists( statfile ): 
            E.warn( "File %s missing" % statfile )
            continue
        lines = [ x for x in open( statfile, "r").readlines() if not x.startswith("#") and x.strip() ]
        if first: outf.write( "%s\t%s" % ("track", lines[0] ) )
        first = False
        outf.write( "%s\t%s" % (track,lines[1] ))

        
    outf.close()
    tmpfilename = outf.name

    statement = '''cat %(tmpfilename)s
                | python %(scriptsdir)s/csv2db.py
                      --index=track
                      --table=%(tablename)s 
                > %(outfile)s
               '''
    P.run()

#########################################################################
#########################################################################
#########################################################################
@transform( dedup, 
            regex( r"(\S+)/bam/(\S+).bam"),
            r"\1/bam/\2.alignstats" )
def buildPicardAlignStats( infile, outfile ):
    '''Gather BAM file alignment statistics using Picard '''
    to_cluster = USECLUSTER
    track = P.snip( os.path.basename(infile), ".bam" )
    statement = '''CollectAlignmentSummaryMetrics INPUT=%(infile)s REFERENCE_SEQUENCE=%%(bwa_index_dir)s/%%(genome)s.fa ASSUME_SORTED=true OUTPUT=%(outfile)s VALIDATION_STRINGENCY=SILENT ''' % locals()
    P.run()

############################################################
############################################################
############################################################
@merge( buildPicardAlignStats, "picard_align_stats.load" )
def loadPicardAlignStats( infiles, outfile ):
    '''Merge Picard alignment stats into single table and load into SQLite.'''

    tablename = P.toTable( outfile )

    outf = P.getTempFile()

    first = True
    for f in infiles:
        track = P.snip( os.path.basename(f), ".dedup.alignstats" )
        if not os.path.exists( f ): 
            E.warn( "File %s missing" % f )
            continue
        lines = [ x for x in open( f, "r").readlines() if not x.startswith("#") and x.strip() ]
        if first: outf.write( "%s\t%s" % ("track", lines[0] ) )
        first = False
        for i in range(1, len(lines)):
            outf.write( "%s\t%s" % (track,lines[i] ))

        
    outf.close()
    tmpfilename = outf.name

    statement = '''cat %(tmpfilename)s
                | python %(scriptsdir)s/csv2db.py
                      --index=track
                      --table=%(tablename)s 
                > %(outfile)s
               '''
    P.run()

    os.unlink( tmpfilename )

#########################################################################
#########################################################################
#########################################################################
@transform( dedup, 
            regex( r"(\S+)/bam/(\S+).bam"),
            r"\1/bam/\2.isizestats" )
def buildPicardInsertSizeStats( infile, outfile ):
    '''Gather BAM file insert size statistics using Picard '''
    to_cluster = USECLUSTER
    track = P.snip( os.path.basename(infile), ".bam" )
    statement = '''CollectInsertSizeMetrics INPUT=%(infile)s REFERENCE_SEQUENCE=%%(bwa_index_dir)s/%%(genome)s.fa ASSUME_SORTED=true OUTPUT=%(outfile)s HISTOGRAM_FILE=%(outfile)s.pdf VALIDATION_STRINGENCY=SILENT ''' % locals()
    P.run()

############################################################
############################################################
############################################################
@merge( buildPicardInsertSizeStats, "picard_isize_stats.load" )
def loadPicardInsertSizeStats( infiles, outfile ):
    '''Merge Picard insert size stats into single table and load into SQLite.'''

    tablename = P.toTable( outfile )
    outf = P.getTempFile()

    first = True
    for f in infiles:
        track = P.snip( os.path.basename(f), ".dedup.isizestats" )
        if not os.path.exists( f ): 
            E.warn( "File %s missing" % f )
            continue
        lines = [ x for x in open( f, "r").readlines() if not x.startswith("#") and x.strip() ]
        if first: outf.write( "%s\t%s" % ("track", lines[0] ) )
        first = False
        outf.write( "%s\t%s" % (track,lines[1] ))
        
    outf.close()
    tmpfilename = outf.name

    statement = '''cat %(tmpfilename)s
                | python %(scriptsdir)s/csv2db.py
                      --index=track
                      --table=%(tablename)s 
                > %(outfile)s
               '''
    P.run()

    os.unlink( tmpfilename )

#########################################################################
#########################################################################
#########################################################################
@transform( dedup, 
            regex(r"(\S+)/bam/(\S+).bam"),
            r"\1/bam/\2.readstats" )
def buildBAMStats( infile, outfile ):
    '''Count number of reads mapped, duplicates, etc. '''
    to_cluster = USECLUSTER
    scriptsdir = PARAMS["general_scriptsdir"]
    statement = '''python %(scriptsdir)s/bam2stats.py --force 
                   --output-filename-pattern=%(outfile)s.%%s < %(infile)s > %(outfile)s'''
    P.run()

#########################################################################
#########################################################################
#########################################################################
@merge( buildBAMStats, "bam_stats.load" )
def loadBAMStats( infiles, outfile ):
    '''Import bam statistics into SQLite'''

    scriptsdir = PARAMS["general_scriptsdir"]
    header = ",".join( [P.snip( os.path.basename(x), ".dedup.readstats") for x in infiles] )
    filenames = " ".join( [ "<( cut -f 1,2 < %s)" % x for x in infiles ] )
    tablename = P.toTable( outfile )
    E.info( "loading bam stats - summary" )
    statement = """python %(scriptsdir)s/combine_tables.py
                      --headers=%(header)s
                      --missing=0
                      --ignore-empty
                   %(filenames)s
                | perl -p -e "s/bin/track/"
                | perl -p -e "s/unique/unique_alignments/"
                | python %(scriptsdir)s/table2table.py --transpose
                | python %(scriptsdir)s/csv2db.py
                      --allow-empty
                      --index=track
                      --table=%(tablename)s 
                > %(outfile)s"""
    P.run()

    for suffix in ("nm", "nh"):
        E.info( "loading bam stats - %s" % suffix )
        filenames = " ".join( [ "%s.%s" % (x, suffix) for x in infiles ] )
        tname = "%s_%s" % (tablename, suffix)
        
        statement = """python %(scriptsdir)s/combine_tables.py
                      --header=%(header)s
                      --skip-titles
                      --missing=0
                      --ignore-empty
                   %(filenames)s
                | perl -p -e "s/bin/%(suffix)s/"
                | python %(scriptsdir)s/csv2db.py
                      --table=%(tname)s 
                      --allow-empty
                >> %(outfile)s """
        P.run()

#########################################################################
#########################################################################
#########################################################################
@transform( dedup,
            regex( r"(\S+)/bam/(\S+).bam"),
            r"\1/bam/\2.cov.bamstats" )
def buildCoverageStats(infiles, outfile):
    '''Generate coverage statistics for regions of interest from a bed file using BAMStats'''
    to_cluster = USECLUSTER
    filename = P.snip( os.path.basename(infiles), ".dedup.bam")
    statement = '''bamstats -i %(infiles)s -o %(outfile)s.tmp -f %%(roi_bed)s; ''' % locals()
    statement += '''awk '{if (NR==1) print "Track\t" $0; else print "%(filename)s\t" $0}' %(outfile)s.tmp > %(outfile)s; 
                        rm %(outfile)s.tmp; ''' % locals()
    #print statement
    P.run()

#########################################################################
#########################################################################
#########################################################################
@merge( buildCoverageStats, "coverage_stats.load" )
def loadCoverageStats( infiles, outfile ):
    '''Import coverage statistics into SQLite'''
    scriptsdir = PARAMS["general_scriptsdir"]
    header = "track,feature,feature_length,cov_mean,cov_median,cov_sd,cov_q1,cov_q3,cov_2_5,cov_97_5,cov_min,cov_max"
    filenames = " ".join(infiles)
    tablename = P.toTable( outfile )
    E.info( "loading coverage stats..." )
    statement = '''cat %(filenames)s | sed -e /Track/D |  sed 's/[ \t]*$//' | sed 's/,//' | sed -e 's/[ \\t]\+/\\t/g' > covstats.txt;
                   cat covstats.txt  | python %(scriptsdir)s/csv2db.py %(csv2db_options)s
                       --allow-empty
                       --header=%(header)s
                       --index=track
                       --index=feature
                       --table=%(tablename)s 
                   > %(outfile)s; '''
    P.run()

#########################################################################
#########################################################################
#########################################################################
#@follows( mkdir( "variants" ) )
#@merge( mapReads, r"variants/all.vcf")
#def callVariantsGroup(infiles, outfile):
#    '''Perform SNV and indel called from gapped alignment using SAMtools '''
 #   to_cluster = USECLUSTER
 #   statement = []
 #   filenames = " ".join(infiles)
 #   statement.append('''samtools mpileup -ugf %%(genome_dir)s/%%(genome)s.fa %(filenames)s | bcftools view -bvcg - > variants/all.bcf; ''' % locals() )
 #   statement.append('''bcftools view variants/all.bcf | vcfutils.pl varFilter %%(variant_filter)s > %(outfile)s; ''' % locals() )
 #   statement.append('''vcf-stats %(outfile)s > variants/all.vcfstats;''' % locals() )
 #   statement = " ".join( statement )
 #   #print statement
 #   P.run()

#########################################################################
#########################################################################
#########################################################################
@transform( dedup, 
            regex(r"(\S+)/bam/(\S+).dedup.bam"), 
            r"\1/variants/\2.vcf.gz" )
def callVariantsSAMtools(infiles, outfile):
    '''Perform SNV and indel calling separately for each bam using SAMtools. '''
    to_cluster = USECLUSTER
    track = P.snip( os.path.basename(infiles), ".dedup.bam")
    try: os.mkdir( '''%(track)s/variants''' % locals() )
    except OSError: pass
    statement = []
    statement.append('''samtools mpileup -ugf %%(genome_dir)s/%%(genome)s.fa %(infiles)s | bcftools view -bvcg - > %(track)s/variants/%(track)s.bcf 2>>%(track)s/variants/samtools.log;''' % locals())
    statement.append('''bcftools view %(track)s/variants/%(track)s.bcf | vcfutils.pl varFilter %%(variant_filter)s | bgzip -c > %(outfile)s 2>>%(track)s/variants/samtools.log;  ''' % locals())
    statement.append('''tabix -p vcf %(outfile)s; 2>>%(track)s/variants/samtools.log; ''' % locals())
    statement.append('''vcf-stats %(outfile)s > %(track)s/variants/%(track)s.vcfstats 2>>%(track)s/variants/samtools.log;''' % locals())
    statement = " ".join( statement )
    P.run()

#########################################################################
#########################################################################
#########################################################################
@follows( mkdir("variants"))
@merge( callVariantsSAMtools, "variants/variants.vcf.gz")
def mergeVCFs(infiles, outfile):
    '''Merge multiple VCF files using VCF-tools. '''
    filenames = " ".join( infiles )
    statement = '''vcf-merge %(filenames)s > variants/variants.vcf 2>>variants/vcfmerge.log; ''' % locals()
    statement += '''bgzip -c variants/variants.vcf > variants/variants.vcf.gz 2>>variants/vcfmerge.log; ''' % locals()
    statement += '''tabix -p vcf variants/variants.vcf.gz; 2>>variants/vcfmerge.log; ''' % locals()
    P.run()

#########################################################################
#########################################################################
#########################################################################
@transform( mergeVCFs,
            regex( r"variants/(\S+).vcf.gz"),
            r"variants/\1.roi.vcf.gz")
def filterVariantsROI(infiles, outfile):
    '''Filter variant calls in vcf format to regions of interest from a bed file'''
    to_cluster = USECLUSTER
    track = P.snip( os.path.basename(infiles), ".vcf.gz")
    infile = P.snip( infiles, ".gz")
    statement  = '''zcat %(infiles)s | intersectBed -u -a stdin -b %%(roi_bed)s > variants/%(track)s.roi.tmp 2>>variants/roi.log; ''' % locals()
    statement += '''(zcat %(infiles)s | grep ^#; cat variants/%(track)s.roi.tmp;) > variants/%(track)s.roi.vcf 2>>variants/roi.log; rm variants/%(track)s.roi.tmp;''' % locals()
    statement += '''bgzip -c variants/%(track)s.roi.vcf > %(outfile)s 2>>variants/roi.log; ''' % locals()
    statement += '''tabix -p vcf %(outfile)s; 2>>variants/roi.log; ''' % locals()
    #print statement
    P.run()

#########################################################################
#########################################################################
#########################################################################
@transform( (mergeVCFs,filterVariantsROI),
            regex( r"variants/(\S+).vcf.gz"),
            r"variants/\1.vcfstats")
def buildVCFstats(infiles, outfile):
    '''Filter variant calls in vcf format to regions of interest from a bed file'''
    to_cluster = USECLUSTER
    statement = '''vcf-stats %(infiles)s > %(outfile)s;''' % locals()
    #print statement
    P.run()

#########################################################################
#########################################################################
#########################################################################
@merge( buildVCFstats, "vcf_stats.load" )
def loadVCFStats( infiles, outfile ):
    '''Import variant statistics into SQLite'''
    scriptsdir = PARAMS["general_scriptsdir"]
    filenames = " ".join(infiles)
    tablename = P.toTable( outfile )
    E.info( "Loading vcf stats..." )
    statement = '''python %(scriptsdir)s/vcfstats2db.py %(filenames)s >> %(outfile)s; '''
    statement += '''cat vcfstats.txt | python %(scriptsdir)s/csv2db.py %(csv2db_options)s --allow-empty --index=track --table=vcf_stats >> %(outfile)s; '''
    statement += '''cat sharedstats.txt | python %(scriptsdir)s/csv2db.py %(csv2db_options)s --allow-empty --index=track --table=vcf_shared_stats >> %(outfile)s; '''
    statement += '''cat indelstats.txt | python %(scriptsdir)s/csv2db.py %(csv2db_options)s --allow-empty --index=track --table=indel_stats >> %(outfile)s; '''
    statement += '''cat snpstats.txt | python %(scriptsdir)s/csv2db.py %(csv2db_options)s --allow-empty --index=track --table=snp_stats >> %(outfile)s; '''
    P.run()

#########################################################################
#########################################################################
#########################################################################
@follows( loadROI,
          loadROI2Gene,
          loadSamples,
          mapReads,
          dedup,
          loadPicardDuplicateStats,
          buildPicardAlignStats,
          loadPicardAlignStats,
          buildPicardInsertSizeStats,
          loadPicardInsertSizeStats,
          buildBAMStats,
          loadBAMStats,
          buildCoverageStats,
          loadCoverageStats,
          callVariantsSAMtools,
          mergeVCFs,
          filterVariantsROI,
          buildVCFstats,
          loadVCFStats )
def full(): pass


@follows( mkdir( "report" ) )
def build_report():
    '''build report from scratch.'''

    E.info( "Starting documentation build process from scratch" )
    dirname, basenme = os.path.split( os.path.abspath( __file__ ) )
    docdir = os.path.join( dirname, "pipeline_docs", P.snip( basenme, ".py" ) )

    # requires libtk, which is not present on the nodes
    to_cluster = True
    job_options= "-pe dedicated %i -R y" % PARAMS["report_threads"]
    statement = '''rm -rf report _cache _static;
                   sphinxreport-build 
                       --num-jobs=%(report_threads)s
                   sphinx-build 
                       -b html 
                       -d %(report_doctrees)s
                       -c . 
                   %(docdir)s %(report_html)s
                   > report.log '''
    P.run()

if __name__== "__main__":
    sys.exit( P.main(sys.argv) )

