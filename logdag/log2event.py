import logging
import pickle
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np

from . import dtutil
from . import arguments
from amulog import common
from amulog import config

_logger = logging.getLogger(__package__)

SRCCLS_LOG = "log"
SRCCLS_SNMP = "snmp"


class EventDefinition(ABC):
    _l_attr = ["source", "host", "group"]

    def __init__(self, **kwargs):
        for attr in self._l_attr:
            setattr(self, attr, kwargs[attr])

    def key(self):
        return None

    @property
    def identifier(self):
        return self.__str__()


class MultipleEventDefinition(EventDefinition):
    _l_attr = []

    def __init__(self, members, **kwargs):
        super().__init__(**kwargs)
        self._members = members

    def __str__(self):
        return "|".join([str(evdef) for evdef in self._members])

    @property
    def members(self):
        return self._members

    @property
    def identifier(self):
        return "|".join(sorted([str(evdef) for evdef in self._members]))

    def all_attr(self, key):
        return {getattr(evdef, key) for evdef in self._members}


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
        self._ermap[evdef.identifier] = eid
        return eid

    def has_eid(self, eid):
        return eid in self._emap

    def has_evdef(self, evdef):
        return evdef.identifier in self._ermap

    def evdef(self, eid):
        return self._emap[eid]

    def items(self):
        return self._emap.items()

    def get_eid(self, evdef):
        return self._ermap[evdef.identifier]

    def iter_eid(self):
        return self._emap.keys()

    def iter_evdef(self):
        for eid in self.iter_eid():
            yield self._emap[eid]

    def dump(self, args):
        fp = arguments.ArgumentManager.evdef_path(args)
        obj = (self._emap, self._ermap)
        with open(fp, "wb") as f:
            pickle.dump(obj, f)

    def load(self, args):
        fp = arguments.ArgumentManager.evdef_path(args)
        try:
            with open(fp, "rb") as f:
                obj = pickle.load(f)
            self._emap, self._ermap = obj
        except:
            # compatibility
            fp = arguments.ArgumentManager.evdef_path_old(args)
            with open(fp, "rb") as f:
                obj = pickle.load(f)
            self._emap, self._ermap = obj


class AreaTest:

    def __init__(self, conf):
        self._arearule = conf["dag"]["area"]
        self._areadict = config.GroupDef(conf["dag"]["area_def"])

        if self._arearule == "all":
            self._testfunc = self._test_all
        elif self._arearule == "each":
            self._testfunc = self._test_each
        else:
            self.areas = config.gettuple(conf, "dag", "area")
            self._testfunc = self._test_ingroup

    @staticmethod
    def _test_all(area, host):
        return True

    @staticmethod
    def _test_each(area, host):
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


def load_event(measure, tags, dt_range, ci_bin_size, ci_bin_diff,
               method, binarize=False, el=None):
    if method == "sequential":
        df = el.load(measure, tags, dt_range, ci_bin_size)
        if df is None or df[el.fields[0]].sum() == 0:
            _logger.debug("{0} is empty".format((measure, tags)))
            return None
        if binarize:
            df[df > 0] = 1
    elif method == "slide":
        tmp_dt_range = (dt_range[0],
                        max(dt_range[1],
                            dt_range[1] + (ci_bin_size - ci_bin_diff)))
        items = list(el.load_items(measure, tags, tmp_dt_range))
        if len(items) == 0:
            _logger.debug("{0} is empty".format((measure, tags)))
            return None
        l_dt = [e[0] for e in items]
        l_array = np.vstack([e[1] for e in items])[:, 0]
        data = dtutil.discretize_slide(l_dt, dt_range, ci_bin_diff,
                                       ci_bin_size, binarize,
                                       l_dt_values=l_array)
        l_dt_label = dtutil.range_dt(dt_range[0], dt_range[1], ci_bin_diff)
        dtindex = pd.to_datetime(l_dt_label)
        df = pd.DataFrame(data, index=dtindex)
    elif method == "radius":
        tmp_dt_range = (min(dt_range[0],
                            dt_range[0] - 0.5 * (ci_bin_size - ci_bin_diff)),
                        max(dt_range[1],
                            dt_range[1] + 0.5 * (ci_bin_size - ci_bin_diff)))
        items = list(el.load_items(measure, tags, tmp_dt_range))
        if len(items) == 0:
            _logger.debug("{0} is empty".format((measure, tags)))
            return None
        l_dt = [e[0] for e in items]
        l_array = np.vstack([e[1] for e in items])[:, 0]
        data = dtutil.discretize_radius(l_dt, dt_range, ci_bin_diff,
                                        0.5 * ci_bin_size, binarize,
                                        l_dt_values=l_array)
        l_dt_label = dtutil.range_dt(dt_range[0], dt_range[1], ci_bin_diff)
        dtindex = pd.to_datetime(l_dt_label)
        df = pd.DataFrame(data, index=dtindex)
    else:
        raise NotImplementedError

    return df


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

    for evdef in el.iter_evdef(dt_range):
        measure, tags = evdef.series()
        if not areatest.test(area, tags["host"]):
            continue
        df = load_event(measure, tags, dt_range, ci_bin_size, ci_bin_diff,
                        method, binarize, el)
        if df is not None:
            yield evdef, df


def load_event_snmp_all(conf, dt_range, area, binarize, d_el=None):
    if d_el is None:
        from .source import evgen_snmp
        el = evgen_snmp.SNMPEventLoader(conf)
    else:
        el = d_el["snmp"]
    areatest = AreaTest(conf)
    method = conf.get("dag", "ci_bin_method")
    ci_bin_size = config.getdur(conf, "dag", "ci_bin_size")
    ci_bin_diff = config.getdur(conf, "dag", "ci_bin_diff")

    l_feature_name = config.getlist(conf, "dag", "snmp_features")
    if len(l_feature_name) == 0:
        l_feature_name = el.all_feature()
    for evdef in el.iter_evdef(l_feature_name):
        measure, tags = evdef.series()
        if not areatest.test(area, tags["host"]):
            continue
        df = load_event(measure, tags, dt_range, ci_bin_size, ci_bin_diff,
                        method, binarize, el)
        if df is not None:
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

    if len(evlist) == 0:
        _logger.warning("No data loaded")
        return None, None

    merge_sync = conf.getboolean("dag", "merge_syncevent")
    if merge_sync:
        merge_sync_rules = config.getlist(conf, "dag", "merge_syncevent_rules")
        evlist, evmap = merge_sync_event(evlist, evmap, merge_sync_rules)

    input_df = pd.concat(evlist, axis=1)
    return input_df, evmap


def merge_sync_event(evlist, evmap, rules):

    from collections import defaultdict
    hashmap = defaultdict(list)
    # make clusters that have completely same values
    for old_eid, df in enumerate(evlist):
        # old_eid = df.columns[0]
        evdef = evmap.evdef(old_eid)

        value_key = tuple(df.iloc[:, 0])
        tmp_key = [value_key,]
        if "source" in rules:
            tmp_key.append(evdef.source)
        if "host" in rules:
            tmp_key.append(evdef.host)
        if "group" in rules:
            tmp_key.append(evdef.group)
        key = tuple(tmp_key)
        hashmap[key].append(old_eid)

    new_evlist = []
    new_evmap = EventDefinitionMap()
    for l_old_eid in hashmap.values():
        l_evdef = [evmap.evdef(eid) for eid in l_old_eid]

        new_evdef = MultipleEventDefinition(l_evdef)
        if "source" in rules:
            new_evdef.source = l_evdef[0].source
        if "host" in rules:
            new_evdef.host = l_evdef[0].host
        if "group" in rules:
            new_evdef.group = l_evdef[0].group
        new_eid = new_evmap.add_evdef(new_evdef)
        new_df = evlist[l_old_eid[0]]
        new_df.columns = [new_eid, ]
        new_evlist.append(new_df)

    _logger.info("merge-syncevent {0} -> {1}".format(len(evmap), len(new_evmap)))
    return new_evlist, new_evmap


def evdef_instruction(conf, evdef, d_el=None):
    if d_el is None:
        d_el = init_evloaders(conf)

    # TODO compatibility to source-failed results
    try:
        source = evdef.source
    except:
        source = "log"
    return d_el[source].instruction(evdef)


def evdef_detail(conf, evdef, dt_range, head, foot,
                 indent=0, log_org=False, d_el=None):
    if d_el is None:
        d_el = init_evloaders(conf)
#    if evdef.source == SRCCLS_LOG:
#        measure = "log_feature"
#    elif evdef.source == SRCCLS_SNMP:
#        raise NotImplementedError("snmp detail not available yet")
#        #measure, key = _snmp_name2tag(evdef.key)
#    else:
#        raise NotImplementedError
    # for compatibility
    try:
        el = d_el[evdef.source]
    except:
        el = d_el["log"]

    try:
        data = list(el.details(evdef, dt_range, log_org))
    except ValueError as e:
        raise e
    #data = list(el.load_items(measure, evdef.tags(), dt_range))
    return common.show_repr(
        data, head, foot, indent=indent,
        strfunc=lambda x: "{0}: {1}".format(x[0], x[1]))


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

