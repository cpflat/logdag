#!/usr/bin/env python
# coding: utf-8

import sys
import os
import logging
import argparse
import configparser

from amulog import config
from amulog import common
from logdag import dtutil

_logger = logging.getLogger(__package__)

DEFAULT_CONFIG = "/".join((os.path.dirname(__file__),
                           "data/loader.conf.default"))


def open_config(ns):
    conf = configparser.ConfigParser()
    conf.read(ns.conf_path)
    config.set_common_logging(conf, logger_name = [__package__],
                              lv = logging.INFO)
    return conf


def _iter_evdb_term(conf):
    w_term = config.getterm(conf, "general", "evdb_whole_term")
    term = config.getdur(conf, "general", "evdb_unit_term")
    return dtutil.iter_term(w_term, term)


def make_evdb_log_all(ns):
    conf = open_config(ns)
    dump_org = ns.org
    dry = ns.dry

    from . import evgen_log
    el = evgen_log.LogEventLoader(conf, dry = dry)
    for term in _iter_evdb_term(conf):
        el.read(term, dump_org = dump_org)


def make_evdb_snmp_all(ns):
    conf = open_config(ns)
    dump_org = ns.org
    dry = ns.dry

    from . import evgen_snmp
    el = evgen_snmp.EventLoader(conf, dry = dry)
    for term in _iter_evdb_term(conf):
        el.read(term, dump_org = dump_org)


# common argument settings
OPT_DEBUG = [["--debug"],
             {"dest": "debug", "action": "store_true",
              "help": "set logging level to debug (default: info)"}]
OPT_CONFIG = [["-c", "--config"],
              {"dest": "conf_path", "metavar": "CONFIG", "action": "store",
               "default": None,
               "help": "configuration file path for amulog"}]
OPT_ORG = [["-o", "--org"],
           {"dest": "org", "action": "store_true",
            "help": "output original data to evdb"}]
OPT_DRY = [["-d", "--dry"],
           {"dest": "dry", "action": "store_true",
            "help": "do not write down to db (dry-run)"}]

# argument settings for each modes
# description, List[args, kwargs], func
# defined after functions because these settings use functions
DICT_ARGSET = {
    "make-evdb-log": ["Load log data from amulog and output features",
                          [OPT_CONFIG, OPT_DEBUG, OPT_ORG, OPT_DRY],
                          make_evdb_log_all],
    "make-evdb-snmp": ["Load SNMP data from rrd and output features",
                           [OPT_CONFIG, OPT_DEBUG, OPT_ORG, OPT_DRY],
                           make_evdb_snmp_all],
}

USAGE_COMMANDS = "\n".join(["  {0}: {1}".format(key, val[0])
                            for key, val in sorted(DICT_ARGSET.items())])
USAGE = ("usage: {0} MODE [options and arguments] ...\n\n"
         "mode:\n".format(sys.argv[0])) + USAGE_COMMANDS + \
    "\n\nsee \"{0} MODE -h\" to refer detailed usage".format(sys.argv[0])

if __name__ == "__main__":
    if len(sys.argv) < 1:
        sys.exit(USAGE)
    mode = sys.argv[1]
    if mode in ("-h", "--help"):
        sys.exit(USAGE)
    commandline = sys.argv[2:]

    desc, l_argset, func = DICT_ARGSET[mode]
    ap = argparse.ArgumentParser(prog = " ".join(sys.argv[0:2]),
                                 description = desc)
    for args, kwargs in l_argset:
        ap.add_argument(*args, **kwargs)
    ns = ap.parse_args(commandline)
    func(ns)

