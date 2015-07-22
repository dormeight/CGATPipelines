'''
PipelineGeneset.py - utility tasks for dealing with ENSEMBL gene sets
=====================================================================

Most of this tasks take a geneset (.gtf.gz) from ENSEMBL
as input.

As of ENSEMBL release 75 the gtf file contains both transcripts but also
untranscribed features such as pseudo genes, for example::

   1       pseudogene      gene    11869   14412   .       +       .       gene_id "ENSG00000223972"; gene_name "DDX11L1"; gene_source "ensembl_havana"; gene_biotype "pseudogene";

For all tasks in this module, only transcript generating features are included.

'''

import os
import collections
import gzip
import sqlite3

import CGAT.IOTools as IOTools
import CGATPipelines.Pipeline as P
import CGAT.Experiment as E
import CGAT.GTF as GTF
import CGAT.IndexedFasta as IndexedFasta

# for UCSC import
import MySQLdb

# When importing this module, set PARAMS to your parameter
# dictionary
PARAMS = {}

ENSEMBL_INFO = collections.namedtuple(
    "ENSEMBLINFO", "species gene_prefix transcript_prefix")

# Map of UCSC genome prefixes to ENSEMBL gene sets
MAP_UCSC2ENSEMBL = {
    'hg': ENSEMBL_INFO._make(('Homo_sapiens',
                              'ENSG',
                              'ENST')),
    'mm': ENSEMBL_INFO._make(('Mus_musculus',
                              'ENSMUSG',
                              'ENSMUST')),
    'rn': ENSEMBL_INFO._make(('Rattus_norvegicus',
                              'ENSRNOG',
                              'ENSRNOT')),
    }


def mapUCSCToEnsembl(genome):
    '''map the name of a UCSC genome (hg19, mm10) to
    ENSEMBL URLs.'''
    prefix = genome[:2]
    return MAP_UCSC2ENSEMBL[prefix]


def connectToUCSC():
    '''connect to UCSC mysql database.'''
    dbhandle = MySQLdb.Connect(host=PARAMS["ucsc_host"],
                               user=PARAMS["ucsc_user"])

    cc = dbhandle.cursor()
    cc.execute("USE %s " % PARAMS["ucsc_database"])

    return dbhandle


def importRefSeqFromUCSC(infile, outfile, remove_duplicates=True):
    '''import gene set from UCSC database
    based on refseq mappings.

    Outputs a gtf-formatted file a la ENSEMBL.

    Depending on *remove_duplicates*, duplicate mappings are either
    removed or kept.

    Matches to chr_random are ignored (as does ENSEMBL).

    Note that this approach does not work as a gene set, as refseq
    maps are not real gene builds and unalignable parts cause
    differences that are not reconcilable.

    '''

    import MySQLdb
    dbhandle = MySQLdb.Connect(host=PARAMS["ucsc_host"],
                               user=PARAMS["ucsc_user"])

    cc = dbhandle.cursor()
    cc.execute("USE %s " % PARAMS["ucsc_database"])

    duplicates = set()

    if remove_duplicates:
        cc.execute("""
        SELECT name, COUNT(*) AS c FROM refGene
        WHERE chrom NOT LIKE '%_random'
        GROUP BY name HAVING c > 1""")
        duplicates = set([x[0] for x in cc.fetchall()])
        E.info("removing %i duplicates" % len(duplicates))

    # these are forward strand coordinates
    statement = '''
        SELECT gene.name, link.geneName, link.name, gene.name2, product,
               protAcc, chrom, strand, cdsStart, cdsEnd,
               exonCount, exonStarts, exonEnds, exonFrames
        FROM refGene as gene, refLink as link
        WHERE gene.name = link.mrnaAcc
              AND chrom NOT LIKE '%_random'
        ORDER by chrom, cdsStart
        '''

    outf = gzip.open(outfile, "w")

    cc = dbhandle.cursor()
    cc.execute(statement)

    SQLResult = collections.namedtuple(
        'Result',
        '''transcript_id, gene_id, gene_name, gene_id2, description,
        protein_id, contig, strand, start, end,
        nexons, starts, ends, frames''')

    counts = E.Counter()
    counts.duplicates = len(duplicates)

    for r in map(SQLResult._make, cc.fetchall()):

        if r.transcript_id in duplicates:
            continue

        starts = map(int, r.starts.split(",")[:-1])
        ends = map(int, r.ends.split(",")[:-1])
        frames = map(int, r.frames.split(",")[:-1])

        gtf = GTF.Entry()
        gtf.contig = r.contig
        gtf.source = "protein_coding"
        gtf.strand = r.strand
        gtf.gene_id = r.gene_id
        gtf.transcript_id = r.transcript_id
        gtf.addAttribute("protein_id", r.protein_id)
        gtf.addAttribute("transcript_name", r.transcript_id)
        gtf.addAttribute("gene_name", r.gene_name)

        assert len(starts) == len(ends) == len(frames)

        if gtf.strand == "-":
            starts.reverse()
            ends.reverse()
            frames.reverse()

        counts.transcripts += 1
        i = 0
        for start, end, frame in zip(starts, ends, frames):
            gtf.feature = "exon"
            counts.exons += 1
            i += 1
            gtf.addAttribute("exon_number", i)
            # frame of utr exons is set to -1 in UCSC
            gtf.start, gtf.end, gtf.frame = start, end, "."
            outf.write("%s\n" % str(gtf))

            cds_start, cds_end = max(r.start, start), min(r.end, end)
            if cds_start >= cds_end:
                # UTR exons have no CDS
                # do not expect any in UCSC
                continue
            gtf.feature = "CDS"
            # invert the frame
            frame = (3 - frame % 3) % 3
            gtf.start, gtf.end, gtf.frame = cds_start, cds_end, frame
            outf.write("%s\n" % str(gtf))

    outf.close()

    E.info("%s" % str(counts))


def annotateGenome(infile, outfile,
                   only_proteincoding=False):
    '''annotate genomic regions with reference gene set.

    *infile* is an ENSEMBL gtf file.
    Only considers protein coding genes, if *only_proteincoding* is set.

    The method applies the following filters:

    * Exons from different transcripts in each gene are merged by overlap.

    * In case of overlapping genes, only take the longest (in genomic
      coordinates) is kept.

    The task outputs a :term:`gff` formatted file in *outfile*. For
    more information, see documentation for the script
    :mod:`gtf2gff.py` under the option ``--method=genome``.

    This method only uses transcribed features.

    '''

    method = "genome"

    if only_proteincoding:
        filter_cmd = """python %(scriptsdir)s/gtf2gtf.py
        --method=filter --filter-method=proteincoding""" % PARAMS
    else:
        filter_cmd = "cat"

    statement = """
    zcat %(infile)s
    | %(filter_cmd)s
    | grep "transcript_id"
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=gene+transcript
    | python %(scriptsdir)s/gtf2gtf.py --method=merge-exons
        --with-utr --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=longest-gene
        --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=position
    | python %(scriptsdir)s/gtf2gff.py
    --genome-file=%(genome_dir)s/%(genome)s
    --log=%(outfile)s.log
    --flank-size=%(enrichment_genes_flank)s
    --method=%(method)s
    | gzip
    > %(outfile)s
    """
    P.run()


def annotateGeneStructure(infile, outfile,
                          only_proteincoding=False):
    '''annotate genomic regions with reference gene set.

    *infile* is an ENSEMBL gtf file.
    Only considers protein coding genes, if *only_proteincoding* is set.

    The method applies the following filters:

    * If there are multiple transcripts in a gene, a representative
      transcript is kept.

    * In case of overlapping genes, only take the longest (in genomic
      coordinates) is kept.

    The task outputs a :term:`gff` formatted file in *outfile*. For
    more information, see documentation for the script
    :mod:`gtf2gff.py` under the option ``--method=genes``.

    This method only uses transcribed features.
    '''

    if only_proteincoding:
        filter_cmd = """python %(scriptsdir)s/gtf2gtf.py
        --method=filter --filter-method=proteincoding""" % PARAMS
    else:
        filter_cmd = "cat"

    method = "genes"

    statement = """
    gunzip
    < %(infile)s
    | %(filter_cmd)s
    | awk '$3 == "exon"'
    | grep "transcript_id"
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=gene+transcript
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=representative-transcript
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=longest-gene
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=position
    | python %(scriptsdir)s/gtf2gff.py
    --genome-file=%(genome_dir)s/%(genome)s
    --log=%(outfile)s.log
    --flank-size=%(enrichment_genestructures_flank)i
    --flank-increment-size=%(enrichment_genestructures_increment)i
    --method=%(method)s
    --gene-detail=exons
    | gzip
    > %(outfile)s
    """
    P.run()


def buildFlatGeneSet(infile, outfile):
    '''build a flattened gene set.

    All transcripts in a gene are merged into a single transcript.

    *infile* is an ENSEMBL gtf file.
    '''
    # sort by contig+gene, as in refseq gene sets, genes on
    # chr_random might contain the same identifier as on chr
    # and hence merging will fail.
    # --permit-duplicates is set so that these cases will be
    # assigned new merged gene ids.

    statement = """gunzip
    < %(infile)s
    | awk '$3 == "exon"'
    | grep "transcript_id"
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort
    --sort-order=contig+gene
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=merge-exons
    --permit-duplicates
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=set-transcript-to-gene
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort
    --sort-order=position+gene
    --log=%(outfile)s.log
    | gzip
    > %(outfile)s
        """
    P.run()


############################################################
# Doesn't filter miscellaneous contigs from mm10
# Function called from pipeline_kamilah, pipeline_snps
# pipeline_polyphen
def buildProteinCodingGenes(infile, outfile):
    '''build a collection of exons from the proteincoding
    section of the ENSEMBL gene set.

    The exons include both CDS and UTR.

    *infile* is an ENSEMBL gtf file.

    The set is filtered in the same way as in
    :meth:`buildGeneRegions`.

    '''

    # sort by contig+gene, as in refseq gene sets, genes on
    # chr_random might contain the same identifier as on chr
    # and hence merging will fail.
    # --permit-duplicates is set so that these cases will be
    # assigned new merged gene ids.
    statement = """zcat %(infile)s
    | python %(scriptsdir)s/gtf2gtf.py --method=filter --filter-method=proteincoding
    | grep "transcript_id"
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=contig+gene
    | python %(scriptsdir)s/gff2gff.py
    --method=sanitize
    --sanitize-method=genome
    --skip-missing
    --genome-file=%(genome_dir)s/%(genome)s
    | python %(scriptsdir)s/gtf2gtf.py
    --method=merge-exons
    --permit-duplicates
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=longest-gene
    --log=%(outfile)s.log
    | awk '$3 == "exon"'
    | python %(scriptsdir)s/gtf2gtf.py
    --method=set-transcript-to-gene
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=gene+transcript
    | gzip
    > %(outfile)s
    """
    P.run()


def loadGeneInformation(infile, outfile, only_proteincoding=False):
    '''load gene information gleaned from the attributes
    in the gene set gtf file.

    *infile* is an ENSEMBL gtf file.
    '''

    table = P.toTable(outfile)

    if only_proteincoding:
        filter_cmd = """python %(scriptsdir)s/gtf2gtf.py
        --method=filter --filter-method=proteincoding""" % PARAMS
    else:
        filter_cmd = "cat"

    load_statement = P.build_load_statement(
        table,
        options="--add-index=gene_id "
        "--add-index=gene_name"
        "--map=gene_name:str")

    statement = '''
    zcat %(infile)s
    | %(filter_cmd)s
    | grep "transcript_id"
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=gene+transcript
    | python %(scriptsdir)s/gtf2tsv.py
    --attributes-as-columns --output-only-attributes -v 0
    | python %(toolsdir)s/csv_cut.py
    --remove exon_id transcript_id transcript_name protein_id exon_number
    | %(pipeline_scriptsdir)s/hsort 1
    | uniq
    | %(load_statement)s
    > %(outfile)s'''

    P.run()


# Note that this method is currently not used
def loadTranscriptInformation(infile, outfile,
                              only_proteincoding=False):
    '''load transcript information from a gtf file.

    *infile* is an ENSEMBL gtf file.
    '''
    table = P.toTable(outfile)

    if only_proteincoding:
        filter_cmd = """python %(scriptsdir)s/gtf2gtf.py
        --method=filter --filter-method=proteincoding""" % PARAMS
    else:
        filter_cmd = "cat"

    load_statement = P.build_load_statement(
        table,
        options="--add-index=gene_id "
        "--add-index=gene_name"
        "--add-index=protein_id"
        "--add-index=transcript_id"
        "--map=gene_name:str")

    statement = '''zcat < %(infile)s
    | awk '$3 == "CDS"'
    | grep "transcript_id"
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=gene+transcript
    | python %(scriptsdir)s/gtf2tsv.py
    --attributes-as-columns --output-only-attributes -v 0
    | python %(toolsdir)s/csv_cut.py --remove exon_id exon_number
    | %(pipeline_scriptsdir)s/hsort 1 | uniq
    | %(load_statement)s
    > %(outfile)s'''
    P.run()


def buildCDNAFasta(infile, outfile):
    '''load ENSEMBL cdna FASTA file

    *infile* is an ENSEMBL cdna file.
    '''
    dbname = outfile[:-len(".fasta")]

    statement = '''gunzip
    < %(infile)s
    | perl -p -e 'if ("^>") { s/ .*//};'
    | python %(scriptsdir)s/index_fasta.py
       --force-output
    %(dbname)s -
    > %(dbname)s.log
    '''

    P.run()

############################################################
############################################################
############################################################


def buildPeptideFasta(infile, outfile):
    '''create ENSEMBL peptide file

    *infile* is an ENSEMBL .pep.all.fa.gz file.
    '''
    dbname = outfile[:-len(".fasta")]

    statement = '''gunzip
    < %(infile)s
    | perl -p -e 'if ("^>") { s/ .*//};'
    | python %(scriptsdir)s/index_fasta.py
       --force-output
    %(dbname)s -
    > %(dbname)s.log
    '''

    P.run()


def loadPeptideSequences(infile, outfile):
    '''load ENSEMBL peptide file into database

    Remove empty sequences (see for example
    transcript:ENSMUST00000151316, ENSMUSP00000118372)

    *infile* is an ENSEMBL .pep.all.fa.gz file.
    '''

    load_statement = P.build_load_statement(
        P.toTable(outfile),
        options="--add-protein_id"
        "--map=protein_id:str")

    statement = '''gunzip
    < %(infile)s
    | perl -p -e 'if ("^>") { s/ .*//};'
    | python %(scriptsdir)s/fasta2fasta.py --method=filter
    --filter-method=min-length=1
    | python %(scriptsdir)s/fasta2table.py --section=length
    --section=sequence
    | perl -p -e 's/id/protein_id/'
    | %(load_statement)s
    > %(outfile)s'''

    P.run()


def buildCDSFasta(infile, outfile):
    '''load ENSEMBL cdna FASTA file

    *infile* is an ENSEMBL cdna file.
    '''

    dbname = outfile[:-len(".fasta")]
    # infile_peptides, infile_cdnas = infiles

    statement = '''gunzip < %(infile)s
    | python %(scriptsdir)s/gff2fasta.py
        --is-gtf
        --genome=%(genome_dir)s/%(genome)s
    | python %(scriptsdir)s/index_fasta.py
    %(dbname)s --force-output -
    > %(dbname)s.log
    '''
    P.run()
    return

    tmpfile = P.getTempFile(".")

    dbhandle = sqlite3.connect(PARAMS["database_name"])
    cc = dbhandle.cursor()
    tmpfile.write("protein_id\ttranscript_id\n")
    tmpfile.write("\n".join(
        ["%s\t%s" % x for x in
         cc.execute(
             "SELECT DISTINCT protein_id, transcript_id "
             "FROM transcript_info")]))
    tmpfile.write("\n")

    tmpfile.close()

    tmpfilename = tmpfile.name

    statement = '''
    python %(scriptsdir)s/peptides2cds.py
           --peptides-fasta-file=%(infile_peptides)s
           --cdnas=%(infile_cdnas)s
           --map=%(tmpfilename)s
           --output-format=fasta
           --log=%(outfile)s.log
    | python %(scriptsdir)s/index_fasta.py
    %(dbname)s --force-output -
    > %(dbname)s.log
    '''

    P.run()
    os.unlink(tmpfilename)


def loadGeneStats(infile, outfile):
    '''load gene statistics to database.

    The *infile* is the *outfile* from :meth:`buildGenes`
    '''

    load_statement = P.build_load_statement(
        P.toTable(outfile),
        options="--add-index=gene_id "
        "--map=gene_name:str")

    statement = '''
    gunzip < %(infile)s
    | python %(scriptsdir)s/gtf2table.py
          --log=%(outfile)s.log
          --genome=%(genome_dir)s/%(genome)s
          --counter=position
          --counter=length
          --counter=composition-na
    | %(load_statement)s
    > %(outfile)s'''
    P.run()


def buildExons(infile, outfile):
    '''build a collection of transcripts from the ENSEMBL gene set.

    Only the exon portion is kept.
    '''
    statement = '''
    gunzip < %(infile)s
    | awk '$3 == "exon"'
    | python %(scriptsdir)s/gtf2gtf.py
    --method=remove-duplicates --duplicate-feature=gene
    --log=%(outfile)s.log
    | gzip > %(outfile)s
    '''
    P.run()


def buildCodingExons(infile, outfile):
    '''build a collection of transcripts from the proteincoding portion
    of the ENSEMBL gene set.

    All exons are kept

    '''

    statement = '''
    zcat %(infile)s
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=proteincoding
    --log=%(outfile)s.log
    | awk '$3 == "exon"'
    | python %(scriptsdir)s/gtf2gtf.py
    --method=remove-duplicates --duplicate-feature=gene
    --log=%(outfile)s.log
    | gzip > %(outfile)s
    '''
    P.run()


def buildNonCodingExons(infile, outfile):
    '''build a collection of transcripts from the non-coding portion of
    the ENSEMBL gene set.

    Transcripts not marked as protein_coding are removed, all
    others are kept.

    All exons are kept
    '''

    statement = '''
    gunzip < %(infile)s
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=proteincoding --invert-filter
    --log=%(outfile)s.log
    | awk '$3 == "exon"'
    | python %(scriptsdir)s/gtf2gtf.py
    --method=remove-duplicates --duplicate-feature=gene
    --log=%(outfile)s.log
    | gzip > %(outfile)s
    '''
    P.run()


def buildLincRNAExons(infile, outfile):
    '''build a collection of transcripts from the LincRNA portion of the
    ENSEMBL gene set. All exons are kept
    '''
    statement = '''
    gunzip < %(infile)s
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=lincrna
    --log=%(outfile)s.log
    | awk '$3 == "exon"'
    | python %(scriptsdir)s/gtf2gtf.py
    --method=remove-duplicates --duplicate-feature=gene
    --log=%(outfile)s.log
    | gzip > %(outfile)s
    '''
    P.run()


def buildCDS(infile, outfile):
    '''build a collection of transcripts from the proteincoding
    section of the ENSEMBL gene set.

    Only CDS exons are parts of exons are output - UTR's are removed.

    Removes any transcripts with very long (> 3Mb) introns.
    '''
    statement = '''
    gunzip < %(infile)s
    | python %(scriptsdir)s/gtf2gtf.py
    --method=filter --filter-method=proteincoding
    --log=%(outfile)s.log
    | awk '$3 == "CDS"'
    | python %(scriptsdir)s/gtf2gtf.py
    --method=remove-duplicates --duplicate-feature=gene
    --log=%(outfile)s.log
    | gzip > %(outfile)s
    '''
    P.run()


def loadTranscripts(infile, outfile):
    '''load the transcript set into the database.
    '''
    load_statement = P.build_load_statement(
        P.toTable(outfile),
        options="--add-index=gene_id "
        "--add-index=transcript_id "
        "--allow-empty-file ")

    # Jethro - some ensembl annotations contain no lincRNAs
    statement = '''
    gunzip < %(infile)s
    | python %(scriptsdir)s/gtf2tsv.py
    | %(load_statement)s
    > %(outfile)s'''
    P.run()


def loadTranscript2Gene(infile, outfile):
    '''build and load a map of transcript to gene from gtf file
    '''
    load_statement = P.build_load_statement(
        P.toTable(outfile),
        options="--add-index=gene_id "
        "--add-index=transcript_id ")

    statement = '''
    gunzip < %(infile)s
    | python %(scriptsdir)s/gtf2tsv.py --output-map=transcript2gene -v 0
    | %(load_statement)s
    > %(outfile)s'''
    P.run()


def loadTranscriptStats(infile, outfile):
    '''load gene statistics to database.

    The *infile* is the *outfile* from :meth:`buildTranscripts`
    '''
    load_statement = P.build_load_statement(
        P.toTable(outfile),
        options="--add-index=gene_id "
        "--add-index=transcript_id "
        "--map=gene_id:str")

    statement = '''
    gunzip < %(infile)s |\
    python %(scriptsdir)s/gtf2table.py \
          --log=%(outfile)s.log \
          --genome=%(genome_dir)s/%(genome)s \
          --reporter=transcripts \
          --counter=position \
          --counter=length \
          --counter=composition-na 
    | %(load_statement)s
    > %(outfile)s'''

    P.run()


def loadProteinStats(infile, outfile):
    '''load protein statistics to database.

    The *infile* is an ENSEMBL peptide file.

    Remove empty sequences (see for example
    transcript:ENSMUST00000151316, ENSMUSP00000118372)

    '''
    load_statement = P.build_load_statement(
        P.toTable(outfile),
        options="--add-index=protein_id "
        "--map=protein_id:str")

    statement = '''
    gunzip < %(infile)s
    | python %(scriptsdir)s/fasta2fasta.py
    --method=filter
    --filter-method=min-length=1
    | python %(scriptsdir)s/fasta2table.py
    --log=%(outfile)s
    --sequence-type=aa
    --section=length
    --section=hid
    --section=aa
    --regex-identifier="(\S+)"
    | sed "s/^id/protein_id/"
    | %(load_statement)s
    > %(outfile)s'''

    P.run()

############################################################
############################################################
############################################################
# Function does not appear to be called from any script in
# the existing src directory
# Doesn't filter miscellaneous contigs from mm10


def buildPromotorRegions(infile, outfile):
    '''annotate promotor regions from reference gene set.'''
    statement = """
    gunzip < %(infile)s
    | python %(scriptsdir)s/gff2gff.py --method=sanitize
    --sanitize-method=genome
    --skip-missing --genome-file=%(genome_dir)s/%(genome)s
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gff.py --method=promotors
    --promotor-size=%(promotor_size)s \
    --genome-file=%(genome_dir)s/%(genome)s
    --log=%(outfile)s.log
    | gzip
    > %(outfile)s
    """
    P.run()

############################################################
############################################################
############################################################
# Function does not appear to be called from any script in
# the existing src directory
# Doesn't filter miscellaneous contigs from mm10


def buildTSSRegions(infile, outfile):
    '''annotate transcription start sites from reference gene set.

    Similar to promotors, except that the witdth is set to 1.
    '''
    statement = """
    gunzip < %(infile)s
    | python %(scriptsdir)s/gff2gff.py --method=sanitize
    --sanitize-method=genome
    --skip-missing
    --genome-file=%(genome_dir)s/%(genome)s --log=%(outfile)s.log
    | python %(scriptsdir)s/gtf2gff.py --method=promotors
    --promotor-size=1 --genome-file=%(genome_dir)s/%(genome)s
    --log=%(outfile)s.log > %(outfile)s
    """
    P.run()


def buildOverlapWithEnsembl(infile, outfile, filename_bed):
    '''compute overlap of genes in ``infile`` with intervals
    in ``filename_bed`` and load into database.

    If ``filename_bed`` has multiple tracks the overlap will
    be computed for each track separately.

    ``infile`` is the output from :meth:`buildGenes`.
    '''

    statement = '''gunzip
        < %(infile)s
        | python %(scriptsdir)s/gtf2gtf.py --method=merge-transcripts
        | python %(scriptsdir)s/gff2bed.py --is-gtf
        | python %(scriptsdir)s/bed2graph.py
            --output-section=name
            --log=%(outfile)s.log
            - %(filename_bed)s
        > %(outfile)s
    '''
    P.run()


def compareGeneSets(infiles, outfile):
    '''compute overlap of genes, exons and transcripts in ``infiles``

    ``infiles`` are protein coding gene sets.
    '''

    infiles = " ".join(infiles)
    statement = '''
        python %(scriptsdir)s/diff_gtf.py
        %(infiles)s
    > %(outfile)s
    '''
    P.run()


def buildPseudogenes(infiles, outfile, dbhandle):
    '''build a set of pseudogenes.

    *infiles* is an ENSEMBL gtf file and a list of associated
    peptide sequences.

    Transcripts are extracted from the GTF file and designated
    as pseudogenes if:

    * the gene_type or transcript_type contains the phrase
      "pseudo". This taken is from the database.

    * the feature is 'processed_transcript' and has similarity to
      protein coding genes. Similarity is assessed by aligning the transcript
      and peptide set against each other with exonerate.

    Pseudogenic transcripts can overlap with protein coding
    transcripts.

    '''

    infile_gtf, infile_peptides_fasta = infiles

    # JJ - there are also 'nontranslated_CDS', but no explanation of these
    if PARAMS["genome"].startswith("dm"):
        E.warn("Ensembl dm genome annotations only contain source"
               " 'pseudogenes' - skipping exonerate step")
        statement = """zcat %(infile_gtf)s
        |awk '$2 ~ /pseudogene/'
        | gzip
        > %(outfile)s"""
        P.run()
        return

    tmpfile1 = P.getTempFilename(shared=True)

    # collect processed transcripts and save as fasta sequences
    statement = '''
    zcat %(infile_gtf)s
    | awk '$2 ~ /processed/'
    | python %(scriptsdir)s/gff2fasta.py
            --is-gtf
            --genome-file=%(genome_dir)s/%(genome)s
            --log=%(outfile)s.log
    > %(tmpfile1)s
    '''

    P.run()

    if P.isEmpty(tmpfile1):
        E.warn("no pseudogenes found")
        os.unlink(tmpfile1)
        P.touch(outfile)
        return

    model = "protein2dna"

    # map processed transcripts against peptide sequences
    statement = '''
    cat %(tmpfile1)s
    | %(cmd-farm)s --split-at-regex=\"^>(\S+)\" --chunk-size=100
    --log=%(outfile)s.log
    "exonerate --target %%STDIN%%
              --query %(infile_peptides_fasta)s
              --model %(model)s
              --bestn 1
              --score 200
              --ryo \\"%%qi\\\\t%%ti\\\\t%%s\\\\n\\"
              --showalignment no --showsugar no --showcigar no --showvulgar no
    "
    | grep -v -e "exonerate" -e "Hostname"
    | gzip > %(outfile)s.links.gz
    '''

    P.run()

    os.unlink(tmpfile1)

    inf = IOTools.openFile("%s.links.gz" % outfile)
    best_matches = {}
    for line in inf:
        peptide_id, transcript_id, score = line[:-1].split("\t")
        score = int(score)
        if transcript_id in best_matches and \
           best_matches[transcript_id][0] > score:
            continue
        best_matches[transcript_id] = (score, peptide_id)

    inf.close()

    E.info("found %i best links" % len(best_matches))
    new_pseudos = set(best_matches.keys())

    cc = dbhandle.cursor()
    known_pseudos = set([x[0] for x in cc.execute(
        """SELECT DISTINCT transcript_id
        FROM transcript_info
        WHERE transcript_biotype like '%pseudo%' OR
        gene_biotype like '%pseudo%' """)])

    E.info("pseudogenes from: processed_transcripts=%i, known_pseudos=%i, "
           "intersection=%i" % (
               (len(new_pseudos),
                len(known_pseudos),
                len(new_pseudos.intersection(known_pseudos)))))

    all_pseudos = new_pseudos.union(known_pseudos)

    c = E.Counter()

    outf = IOTools.openFile(outfile, "w")
    inf = GTF.iterator(IOTools.openFile(infile_gtf))
    for gtf in inf:
        c.input += 1
        if gtf.transcript_id not in all_pseudos:
            continue
        c.output += 1
        outf.write("%s\n" % gtf)
    outf.close()

    E.info("exons: %s" % str(c))


def buildNUMTs(infile, outfile):
    '''build annotation with nuclear mitochondrial sequences.

    map mitochondrial chromosome against genome using
    exonerate
    '''
    if not PARAMS["numts_mitochrom"]:
        E.info("skipping numts creation")
        P.touch(outfile)
        return

    fasta = IndexedFasta.IndexedFasta(
        os.path.join(PARAMS["genome_dir"], PARAMS["genome"]))

    if PARAMS["numts_mitochrom"] not in fasta:
        E.warn("mitochondrial genome %s not found" % PARAMS["numts_mitochrom"])
        P.touch(outfile)
        return

    tmpfile_mito = P.getTempFilename(".")

    statement = '''
    python %(scriptsdir)s/index_fasta.py
           --extract=%(numts_mitochrom)s
           --log=%(outfile)s.log
           %(genome_dir)s/%(genome)s
    > %(tmpfile_mito)s
    '''

    P.run()

    if P.isEmpty(tmpfile_mito):
        E.warn("mitochondrial genome empty.")
        os.unlink(tmpfile_mito)
        P.touch(outfile)
        return

    format = ("qi", "qS", "qab", "qae",
              "ti", "tS", "tab", "tae",
              "s",
              "pi",
              "C")

    format = "\\\\t".join(["%%%s" % x for x in format])

    # collect all results
    min_score = 100

    statement = '''
    cat %(genome_dir)s/%(genome)s.fasta
    | %(cmd-farm)s --split-at-regex=\"^>(\S+)\" --chunk-size=1
    --log=%(outfile)s.log
    "exonerate --target %%STDIN%%
              --query %(tmpfile_mito)s
              --model affine:local
              --score %(min_score)i
              --showalignment no --showsugar no --showcigar no
              --showvulgar no
              --ryo \\"%(format)s\\n\\"
    "
    | grep -v -e "exonerate" -e "Hostname"
    | gzip > %(outfile)s.links.gz
    '''

    P.run()

    # convert to gtf
    inf = IOTools.openFile("%s.links.gz" % outfile)
    outf = IOTools.openFile(outfile, "w")

    min_score = PARAMS["numts_score"]

    c = E.Counter()

    for line in inf:
        (query_contig, query_strand, query_start, query_end,
         target_contig, target_strand, target_start, target_end,
         score, pid, alignment) = line[:-1].split("\t")

        c.input += 1
        score = int(score)
        if score < min_score:
            c.skipped += 1
            continue

        if target_strand == "-":
            target_start, target_end = target_end, target_start

        gff = GTF.Entry()
        gff.contig = target_contig
        gff.start, gff.end = int(target_start), int(target_end)
        assert gff.start < gff.end

        gff.strand = target_strand
        gff.score = int(score)
        gff.feature = "numts"
        gff.gene_id = "%s:%s-%s" % (query_contig, query_start, query_end)
        gff.transcript_id = "%s:%s-%s" % (query_contig, query_start, query_end)
        outf.write("%s\n" % str(gff))
        c.output += 1

    inf.close()
    outf.close()

    E.info("filtering numts: %s" % str(c))

    os.unlink(tmpfile_mito)


def sortGTF(infile, outfile, order="contig+gene"):
    '''sort a gtf file - the sorting is performed on the cluster.

    Ssee gtf2gtf.py for valid options for order.
    '''
    if infile.endswith(".gz"):
        uncompress = "zcat"
    else:
        # wastefull
        uncompress = "cat"

    if outfile.endswith(".gz"):
        compress = "gzip"
    else:
        compress = "cat"

    job_memory = "4G"

    statement = '''%(uncompress)s %(infile)s
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=%(order)s --log=%(outfile)s.log
    | %(compress)s > %(outfile)s'''

    P.run()


def buildGenomicFunctionalAnnotation(gtffile, dbh, outfiles):
    '''output a bed file with genomic regions with functional annotations.

    The regions for each gene are given in the gtf file.

    Each bed entry is a gene territory. Bed entries are labeled
    by functional annotations associated with a gene.

    Ambiguities in territories are resolved by outputting
    annotations for all genes within a territory.

    The output file contains annotations for both GO and GOSlim. These
    are prefixed by ``go:`` and ``goslim:``.
    '''
    territories_file = gtffile

    outfile_bed, outfile_tsv = outfiles

    gene2region = {}
    for gtf in GTF.iterator(IOTools.openFile(gtffile, "r")):
        gid = gtf.gene_id.split(":")
        for g in gid:
            gene2region[g] = (gtf.contig, gtf.start, gtf.end, gtf.strand)

    cc = dbh.cursor()

    outf = P.getTempFile(".")
    c = E.Counter()
    term2description = {}
    for db in ('go', 'goslim'):
        for gene_id, go_id, description in cc.execute(
                "SELECT gene_id, go_id, description FROM %s_assignments" % db):
            try:
                contig, start, end, strand = gene2region[gene_id]
            except KeyError:
                c.notfound += 1
                continue
            outf.write(
                "\t".join(map(str, (
                    contig, start, end,
                    "%s:%s" % (db, go_id), 1, strand))) + "\n")
            term2description["%s:%s" % (db, go_id)] = description
    outf.close()
    tmpfname = outf.name
    statement = '''sort -k1,1 -k2,2n  < %(tmpfname)s | uniq
    | gzip > %(outfile_bed)s'''

    P.run()

    outf = IOTools.openFile(outfile_tsv, "w")
    outf.write("term\tdescription\n")
    for term, description in term2description.iteritems():
        outf.write("%s\t%s\n" % (term, description))
    outf.close()

    os.unlink(tmpfname)


def buildGenomicContext(infiles, outfile):
    '''build a file with genomic context.

    The output is a bed formatted file, annotating genomic segments
    according to whether they are any of the ENSEMBL annotations.

    It also adds the RNA and repeats annotations from the UCSC.

    The annotations can be partially or fully overlapping.

    Adjacent features (less than 10 bp apart) of the same type are merged.
    '''

    repeats_gff, rna_gff, annotations_gtf, geneset_flat_gff, \
        cpgisland_bed, go_tsv = infiles

    tmpfile = P.getTempFilename(shared=True)
    tmpfiles = ["%s_%i" % (tmpfile, x) for x in range(6)]

    distance = 10

    # add ENSEMBL annotations
    statement = """
    zcat %(annotations_gtf)s
    | python %(scriptsdir)s/gtf2gtf.py
    --method=sort --sort-order=gene
    | python %(scriptsdir)s/gtf2gtf.py
    --method=merge-exons --log=%(outfile)s.log
    | python %(scriptsdir)s/gff2bed.py
    --set-name=gene_biotype --is-gtf
    --log=%(outfile)s.log
    | sort -k 1,1 -k2,2n
    | python %(scriptsdir)s/bed2bed.py --method=merge --merge-by-name
    --merge-distance=%(distance)i --log=%(outfile)s.log
    > %(tmpfile)s_0
    """
    P.run()

    # rna
    statement = '''
    zcat %(repeats_gff)s %(rna_gff)s
    | python %(scriptsdir)s/gff2bed.py --set-name=family --is-gtf -v 0
    | sort -k1,1 -k2,2n
    | python %(scriptsdir)s/bed2bed.py --method=merge --merge-by-name
    --merge-distance=%(distance)i --log=%(outfile)s.log
    > %(tmpfile)s_1'''
    P.run()

    # add aggregate intervals for repeats
    statement = '''
    zcat %(repeats_gff)s
    | python %(scriptsdir)s/gff2bed.py --set-name=family --is-gtf -v 0
    | awk -v OFS="\\t" '{$4 = "repeats"; print}'
    | sort -k1,1 -k2,2n
    | python %(scriptsdir)s/bed2bed.py --method=merge --merge-by-name
    --merge-distance=%(distance)i --log=%(outfile)s.log
    > %(tmpfile)s_2'''
    P.run()

    # add aggregate intervals for rna
    statement = '''
    zcat %(rna_gff)s
    | python %(scriptsdir)s/gff2bed.py --set-name=family --is-gtf -v 0
    | awk -v OFS="\\t" '{$4 = "repetetive_rna"; print}'
    | sort -k1,1 -k2,2n
    | python %(scriptsdir)s/bed2bed.py --method=merge --merge-by-name
    --merge-distance=%(distance)i --log=%(outfile)s.log
    > %(tmpfile)s_3 '''
    P.run()

    # add ribosomal protein coding genes
    goids = ("GO:0003735", )

    patterns = "-e %s" % ("-e ".join(goids))

    statement = '''
    zcat %(geneset_flat_gff)s
    | python %(scriptsdir)s/gtf2gtf.py
    --map-tsv-file=<(zcat %(go_tsv)s | grep %(patterns)s | cut -f 2 | sort | uniq)
    --method=filter --filter-method=gene
    --log=%(outfile)s.log
    | python %(scriptsdir)s/gff2bed.py
    --log=%(outfile)s.log
    | awk -v OFS="\\t" '{$4 = "ribosomal_coding"; print}'
    | sort -k1,1 -k2,2n
    | python %(scriptsdir)s/bed2bed.py --method=merge --merge-by-name
    --merge-distance=%(distance)i --log=%(outfile)s.log
    > %(tmpfile)s_4
    '''
    P.run()

    # CpG islands
    statement = '''
    zcat %(cpgisland_bed)s
    | awk '{printf("%%s\\t%%i\\t%%i\\tcpgisland\\n", $1,$2,$3 )}'
    > %(tmpfile)s_5
    '''
    P.run()

    # sort and merge
    # remove strand information as bedtools
    # complains if there are annotations with
    # different number of field
    files = " ".join(tmpfiles)
    statement = '''
    sort --merge -k1,1 -k2,2n %(files)s
    | cut -f 1-4
    | gzip
    > %(outfile)s
    '''
    P.run()

    for x in tmpfiles:
        os.unlink(x)
