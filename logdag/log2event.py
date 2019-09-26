#!/usr/bin/env python
# coding: utf-8

import logging
import pickle
import pandas as pd
from collections import namedtuple

from . import dtutil
from . import arguments
from amulog import common
from amulog import config

_logger = logging.getLogger(__package__)

SRCCLS_LOG = "log"
SRCCLS_SNMP = "snmp"


class EventDefinition(object):
    _l_attr = ["source", "host", "group"]

    def __init__(self, **kwargs):
        for attr in self._l_attr:
            setattr(self, attr, kwargs[attr])

    def key(self):
        return None


class EventDefinitionMap(object):
    """This class defines classified groups as "Event", and provide
    interconvirsion functions between Event IDs and their
    classifying criterions.

    The definition of Event is saved as a nametuple EvDef.
    Evdef has following attributes.
        source (str):
        key (int): 
        host (str):
        label (str):

    """

    def __init__(self):
        self._emap = {}  # key : eid, val : evdef
        self._ermap = {}  # key : evdef, val : eid

    def __len__(self):
        return len(self._emap)

    def eids(self):
        return self._emap.keys()

    def _next_eid(self):
        eid = len(self._emap)
        while eid in self._emap:
            eid += 1
        else:
            return eid

    def add_evdef(self, evdef):
        eid = self._next_eid()
        self._emap[eid] = evdef
        self._ermap[evdef] = eid
        return eid

    def has_eid(self, eid):
        return eid in self._emap

    def has_evdef(self, evdef):
        return evdef in self._ermap

    def evdef(self, eid):
        return self._emap[eid]

    def items(self):
        return self._emap.items()

    def get_eid(self, info):
        return self._ermap[info]

    def iter_eid(self):
        return self._emap.keys()

    def iter_evdef(self):
        return self._ermap.keys()

    def dump(self, args):
        fp = arguments.ArgumentManager.evdef_filepath(args)
        obj = (self._emap, self._ermap)
        with open(fp, "wb") as f:
            pickle.dump(obj, f)

    def load(self, args):
        fp = arguments.ArgumentManager.evdef_filepath(args)
        with open(fp, "rb") as f:
            obj = pickle.load(f)
        self._emap, self._ermap = obj


class AreaTest():

    def __init__(self, conf):
        self._arearule = conf["dag"]["area"]
        self._areadict = config.GroupDef(conf["dag"]["area_def"])

        if self._arearule == "all":
            self._testfunc = self._test_all

    def _test_all(self, area, host):
        return True

    def _test_each(self, area, host):
        return area == host

    def _test_ingroup(self, area, host):
        return self._areadict.ingroup(area, host)

    def test(self, area, host):
        return self._testfunc(area, host)


def init_evloader(conf, src):
    if src == SRCCLS_LOG:
        from .source import evgen_log
        return evgen_log.LogEventLoader(conf)
    elif src == SRCCLS_SNMP:
        from .source import evgen_snmp
        return evgen_snmp.SNMPEventLoader(conf)
    else:
        raise NotImplementedError


def init_evloaders(conf):
    return {src: init_evloader(conf, src)
            for src in config.getlist(conf, "dag", "source")}


def load_event_log_all(conf, dt_range, area, binarize, d_el=None):
    if d_el is None:
        from .source import evgen_log
        el = evgen_log.LogEventLoader(conf)
    else:
        el = d_el[SRCCLS_LOG]

    areatest = AreaTest(conf)
    method = conf.get("dag", "ci_bin_method")
    ci_bin_size = config.getdur(conf, "dag", "ci_bin_size")
    ci_bin_diff = config.getdur(conf, "dag", "ci_bin_diff")

    for evdef in el.iter_evdef(dt_range, area):
        measure, tags = evdef.series()

        if method == "sequential":
            df = el.load(measure, tags, dt_range, ci_bin_size)
            if df is None or df[el.fields[0]].sum() == 0:
                _logger.debug("{0} is empty".format((measure, tags)))
                continue
            if binarize:
                df[df > 0] = 1
        elif method == "slide":
            l_dt, l_array = zip(*el.load_items(measure, tags, dt_range))
            data = dtutil.discretize_slide(l_dt, dt_range, ci_bin_diff,
                                           ci_bin_size, binarize,
                                           l_dt_values=l_array)
            df = pd.DataFrame(data, index=pd.to_datetime(l_dt))
            if df is None or sum(df) == 0:
                _logger.debug("{0} is empty".format((measure, tags)))
                continue
        elif method == "radius":
            ci_bin_radius = 0.5 * ci_bin_size
            l_dt, l_array = zip(*el.load_items(measure, tags, dt_range))
            data = dtutil.discretize_radius(l_dt, dt_range, ci_bin_diff,
                                            ci_bin_radius, binarize,
                                            l_dt_values=l_array)
            df = pd.DataFrame(data, index=pd.to_datetime(l_dt))
            if df is None or sum(df) == 0:
                _logger.debug("{0} is empty".format((measure, tags)))
                continue
        else:
            raise NotImplementedError

        yield evdef, df


def load_event_snmp_all(conf, dt_range, area, binarize, d_el=None):
    if d_el is None:
        from .source import evgen_snmp
        el = evgen_snmp.SNMPEventLoader(conf)
    else:
        el = d_el["snmp"]
    areatest = AreaTest(conf)
    ci_bin_size = config.getdur(conf, "dag", "ci_bin_size")

    l_feature_name = config.getlist(conf, "dag", "snmp_features")
    if len(l_feature_name) == 0:
        l_feature_name = el.all_feature()
        # l_feature_name = None
    for evdef in el.iter_evdef(l_feature_name):
        measure, tags = evdef.series()
        if not areatest.test(area, tags["host"]):
            continue
        df = el.load(measure, tags, dt_range, ci_bin_size)
        if df is None or df[el.fields[0]].sum() == 0:
            _logger.debug("{0} is empty".format((measure, tags)))
            continue
        if binarize:
            df[df > 0] = 1
        yield evdef, df


def load_event_all(sources, conf, dt_range, area, binarize):
    for src in sources:
        if src == SRCCLS_LOG:
            for evdef, df in load_event_log_all(conf, dt_range, area, binarize):
                yield evdef, df
        elif src == SRCCLS_SNMP:
            for evdef, df in load_event_snmp_all(conf, dt_range, area, binarize):
                yield evdef, df
        else:
            raise NotImplementedError


def makeinput(conf, dt_range, area, binarize):
    evmap = EventDefinitionMap()
    evlist = []
    sources = config.getlist(conf, "dag", "source")
    for evdef, df in load_event_all(sources, conf, dt_range, area, binarize):
        eid = evmap.add_evdef(evdef)
        df.columns = [eid, ]
        evlist.append(df)
        msg = "loaded event {0} {1} (sum: {2})".format(eid, evmap.evdef(eid),
                                                       df[eid].sum())
        _logger.debug(msg)
    input_df = pd.concat(evlist, axis=1)
    return input_df, evmap


def evdef_instruction(conf, evdef, d_el=None):
    if d_el is None:
        d_el = init_evloaders(conf)
    return d_el[evdef.source].instruction(evdef)

# def evdef_detail(conf, evdef, dt_range, head, foot, d_el=None):
#    if d_el is None:
#        d_el = init_evloaders(conf)
#    if evdef.source == SRCCLS_LOG:
#        measure = "log_feature"
#        key = evdef.key
#    elif evdef.source == SRCCLS_SNMP:
#        measure, key = _snmp_name2tag(evdef.key)
#    else:
#        raise NotImplementedError
#    el = d_el[evdef.source]
#    tags = {"host": evdef.host, "key": evdef.key()}
#    data = list(el.load_items(measure, evdef.host, key, dt_range))
#    return common.show_repr(
#        data, head, foot,
#        strfunc=lambda x: "{0}: {1}".format(x[0], x[1]))
#
#
# def evdef_detail_org(conf, evdef, dt_range, head, foot, d_el=None):
#    if d_el is None:
#        d_el = init_evloaders(conf)
#    if evdef.source == SRCCLS_LOG:
#        el = d_el[source]
#        ev = (host, key)
#        data = list(el.load_org(ev, dt_range))
#        return common.show_repr(
#            data, head, foot,
#            strfunc=lambda x: "{0} {1} {2}".format(x[0], x[1], x[2]))
#    elif evdef.source == SRCCLS_SNMP:
#        el = d_el[source]
#        measure, key = _snmp_name2tag(evdef.key)
#        data = list(el.load_org(measure, host, key, dt_range))
#        return common.show_repr(
#            data, head, foot,
#            strfunc=lambda x: "{0}: {1}".format(x[0], x[1]))
#    else:
#        raise NotImplementedError
