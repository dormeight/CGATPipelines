import pandas as pd
import numpy as np

from CGATReport.Tracker import SingleTableTrackerRows
from CGATReport.Tracker import SingleTableTrackerHistogram
from CGATReport.Tracker import *
from CGATReport.Utils import PARAMS as P

from IsoformReport import *


class imagesTracker(TrackerImages):

    '''Convience Tracker for globbing images for gallery plot'''
    def __init__(self, *args, **kwargs):
        Tracker.__init__(self, *args, **kwargs)
        if "glob" not in kwargs:
            raise ValueError("TrackerImages requires a:glob: parameter")
        self.glob = kwargs["glob"]


class simulationCorrelations(IsoformTracker):

    def __call__(self, track, slice=None):

        statement = '''
        SELECT read_count, est_counts, fraction_bin, cor, log2diff,
        log2diff_thres FROM simulation_correlations
        '''

        return self.getAll(statement)


class simulationCorrelationsSummaryFold(IsoformTracker):

    def __call__(self, track, slice=None):

        statement = '''
        select
        total(CASE WHEN abs(log2diff) >0.585 THEN 1 ELSE 0 END) AS 'flagged',
        total(CASE WHEN abs(log2diff) <=0.585 THEN 1 ELSE 0 END) AS 'passed'
        FROM simulation_correlations
        '''

        return self.getAll(statement)


class simulationCorrelationsSummaryKmers(IsoformTracker):

    def __call__(self, track, slice=None):

        statement = '''
        select
        total(CASE WHEN fraction_unique <0.03 THEN 1 ELSE 0 END) AS 'flaged',
        total(CASE WHEN fraction_unique >=0.03 THEN 1 ELSE 0 END) AS 'passed'
        FROM simulation_correlations
        '''

        return self.getAll(statement)
