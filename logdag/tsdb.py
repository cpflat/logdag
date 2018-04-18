#!/usr/bin/env python
# coding: utf-8

import logging
import math
import numpy as np

from . import dtutil
from . import period
from amulog import config
from amulog import db_common

_logger = logging.getLogger(__package__)


class TimeSeriesDB():

    def __init__(self, conf, edit = False, reset_db = False):
        self.areafn = conf.get("database", "area_filename")

        db_type = conf.get("database_ts", "database")
        if db_type == "sqlite3":
            dbpath = conf.get("database_ts", "sqlite3_filename")
            self.db = db_common.sqlite3(dbpath)
        elif db_type == "mysql":
            host = conf.get("database_ts", "mysql_host")
            dbname = conf.get("database_ts", "mysql_dbname")
            user = conf.get("database_ts", "mysql_user")
            passwd = conf.get("database_ts", "mysql_passwd")
            self.db = db_common.mysql(host, dbname, user, passwd)
        else:
            raise ValueError("invalid database type ({0})".format(
                    db_type))

        if self.db.db_exists():
            if not self._exists_tables():
                self._init_tables()
        else:
            self._init_tables()

    def reset_tables(self):
        if self._exists_tables():
            self._drop_tables(self)
            self._init_tables()

    def _exists_tables(self):
        tables = ["ts"]
        s_name = set(self.db.get_table_names())
        for table in tables:
            if not table in s_name:
                return False
        else:
            return True

    def _init_tables(self):
        table_name = "ts"
        l_key = [db_common.tablekey("tid", "integer",
                    ("primary_key", "auto_increment", "not_null")),
                 db_common.tablekey("dt", "datetime"),
                 db_common.tablekey("gid", "integer"),
                 db_common.tablekey("host", "text")]
        sql = self.db.create_table_sql(table_name, l_key)
        self.db.execute(sql)

        table_name = "area"
        l_key = [db_common.tablekey("defid", "integer",
                    ("primary_key", "auto_increment", "not_null")),
                 db_common.tablekey("host", "text"),
                 db_common.tablekey("area", "text")]
        sql = self.db.create_table_sql(table_name, l_key)
        self.db.execute(sql)

        table_name = "filter"
        l_key = [db_common.tablekey("qid", "integer",
                    ("primary_key", "auto_increment", "not_null")),
                 db_common.tablekey("dts", "datetime"),
                 db_common.tablekey("dte", "datetime"),
                 db_common.tablekey("gid", "integer"),
                 db_common.tablekey("host", "text"),
                 db_common.tablekey("stat", "text"),
                 db_common.tablekey("val", "integer"),]
        sql = self.db.create_table_sql(table_name, l_key)
        self.db.execute(sql)

        self._init_index()

    def _init_index(self):
        l_table_name = self.db.get_table_names()

        table_name = "ts"
        index_name = "ts_index"
        l_key = [db_common.tablekey("tid", "integer"),
                 db_common.tablekey("dt", "datetime"),
                 db_common.tablekey("gid", "integer"),
                 db_common.tablekey("host", "text", (100, ))]
        if not index_name in l_table_name:
            sql = self.db.create_index_sql(table_name, index_name, l_key)
            self.db.execute(sql)

        table_name = "area"
        index_name = "area_index"
        l_key = [db_common.tablekey("area", "text", (100, ))]
        if not index_name in l_table_name:
            sql = self.db.create_index_sql(table_name, index_name, l_key)
            self.db.execute(sql)

        table_name = "filter"
        index_name = "filter_index"
        l_key = [db_common.tablekey("dts", "datetime"),
                 db_common.tablekey("dte", "datetime"),
                 db_common.tablekey("gid", "integer"),
                 db_common.tablekey("host", "text", (100, )),
                 db_common.tablekey("stat", "text", (100, )),
                 db_common.tablekey("val", "integer"),]
        if not index_name in l_table_name:
            sql = self.db.create_index_sql(table_name, index_name, l_key)
            self.db.execute(sql)

    def _drop_tables(self):
        table_name = "ts"
        sql = self.db.drop_sql(table_name)
        self.db.execute(sql)
        
        table_name = "area"
        sql = self.db.drop_sql(table_name)
        self.db.execute(sql)

    def _init_area(self):
        # ported from amulog db...
        if self.areafn is None or self.areafn == "":
            return
        areadict = config.GroupDef(self.areafn)
        table_name = "area"
        l_ss = [db_common.setstate("host", "host"),
                db_common.setstate("area", "area")]
        sql = self.db.insert_sql(table_name, l_ss)
        for area, host in areadict.iter_def():
            args = {
                "host" : host,
                "area" : area
            }
            self.db.execute(sql, args)
        self.commit()

    def commit(self):
        self.db.commit()

    def add_line(self, dt, gid, host):
        table_name = "ts"
        d_val = {
            "dt" : self.db.strftime(dt),
            "gid" : gid,
            "host" : host,
        }
        l_ss = [db_common.setstate(k, k) for k in d_val.keys()]
        sql = self.db.insert_sql(table_name, l_ss)
        self.db.execute(sql, d_val)

    def add_filterlog(self, dt_range, gid, host, stat, val):
        table_name = "filter"
        d_val = {
            "dts" : dt_range[0],
            "dte" : dt_range[1],
            "gid" : gid,
            "host" : host,
            "stat" : stat,
            "val" : val,
        }
        l_ss = [db_common.setstate(k, k) for k in d_val.keys()]
        sql = self.db.insert_sql(table_name, l_ss)
        self.db.execute(sql, d_val)

    def iter_ts(self, **kwargs):
        if kwargs["area"] is None or kwargs["area"] == "all":
            del kwargs["area"]
        elif area[:5] == "host_":
            assert not "host" in kwargs
            d_cond["host"] = area[5:]
            del kwargs["area"]
        else:
            d_cond["area"] = area

        if len(kwargs) == 0:
            raise ValueError("More than 1 argument should NOT be None")

        for row in self._select_ts(["tid", "dt"], **kwargs):
            tid = int(row[0])
            dt = self.db.datetime(row[1])
            yield dt

    def _select_ts(self, l_key, **kwargs):
        table_name = "ts"
        l_key = ["tid", "dt", "gid", "host"]
        l_cond = []
        for c in kwargs.keys():
            if c == "top_dt":
                l_cond.append(db_common.cond("dt", ">=", c))
                args[c] = self.db.strftime(d_cond[c])
            elif c == "end_dt":
                l_cond.append(db_common.cond("dt", "<", c))
                args[c] = self.db.strftime(d_cond[c])
            elif c == "area":
                sql = self.db.select_sql("area", ["host"],
                        [db_common.cond(c, "=", c)])
                l_cond.append(db_common.cond("host", "in", sql, False))
            else:
                l_cond.append(db_common.cond(c, "=", c))
        sql = self.db.select_sql(table_name, l_key, l_cond)
        return self.db.execute(sql, args)
    
    def iter_filter(self, **kwargs):
        if kwargs["area"] is None or kwargs["area"] == "all":
            del kwargs["area"]
        elif area[:5] == "host_":
            assert not "host" in kwargs
            d_cond["host"] = area[5:]
            del kwargs["area"]
        else:
            d_cond["area"] = area

        if len(kwargs) == 0:
            raise ValueError("More than 1 argument should NOT be None")

        for row in self._select_filter(["dt"], **kwargs):
            qid = int(row[0])
            dts = self.db.datetime(row[1])
            dte = self.db.datetime(row[2])
            gid = int(row[3])
            host = row[4]
            stat = row[5]
            val = int(row[6])
            yield FilterLog((dts, dte), gid, host, stat, val)

    def _select_filter(self, l_key, **kwargs):
        table_name = "ts"
        l_key = ["qid", "dts", "dte", "gid", "host", "stat", "val"]
        l_cond = []
        for c in kwargs.keys():
            if c == "area":
                sql = self.db.select_sql("area", ["host"],
                        [db_common.cond(c, "=", c)])
                l_cond.append(db_common.cond("host", "in", sql, False))
            else:
                l_cond.append(db_common.cond(c, "=", c))
        sql = self.db.select_sql(table_name, l_key, l_cond)
        return self.db.execute(sql, args)

    def count_lines(self):
        table_name = "ts"
        l_key = ["max(tid)"]
        sql = self.db.select_sql(table_name, l_key)
        cursor = self.db.execute(sql)
        return int(cursor.fetchone()[0])

    def dt_term(self):
        table_name = "ts"
        l_key = ["min(dt)", "max(dt)"]
        sql = self.db.select_sql(table_name, l_key)
        cursor = self.db.execute(sql)
        top_dtstr, end_dtstr = cursor.fetchone()
        if None in (top_dtstr, end_dtstr):
            raise ValueError("No data found in DB")
        return self.db.datetime(top_dtstr), self.db.datetime(end_dtstr)


class FilterLog():

    def __init__(self, dt_range, gid, host, stat, val):
        # stats: none, const, period
        # const: val = counts/day, period : val = interval(seconds)
        self.dt_range = dt_range
        self.gid = gid
        self.host = host
        self.stat = stat
        self.val = val

    def __str__(self):
        return "{0}, gid={1}, host={2}: {3}[4]".format(
            self.dt_range[0].date(), self.gid, self.host, self.stat, self.val)


def log2ts(conf, dt_range):
    gid_name = conf.get("dag", "event_gid")
    usefilter = conf.getboolean("database_ts", "usefilter")
    top_dt, end_dt = dt_range
    
    from amulog import log_db
    ld = log_db.LogData(conf)
    if gid_name == "ltid":
        iterobj = ld.whole_host_lt(top_dt, end_dt, "all")
    elif gid_name == "ltgid":
        iterobj = ld.whole_host_ltg(top_dt, end_dt, "all")
    else:
        raise NotImplementedError

    for host, gid in iterobj:
        # load time-series from db
        d = {gid_name: gid,
             "host": host,
             "top_dt": top_dt,
             "end_dt": end_dt}
        iterobj = ld.iter_lines(**d)
        l_dt = [line.dt for line in iterobj]
        del iterobj
        _logger.debug("gid {0}, host {1}: {2} counts".format(gid, host,
                                                             len(l_dt)))
        assert len(l_dt) > 0

        # apply preprocessing(filter)
        evdef = (gid, host)
        stat, new_l_dt, val = apply_filter(conf, ld, l_dt, dt_range, evdef)

        # update database
        td = TimeSeriesDB(conf, edit = True)
        for dt in new_l_dt:
            td.add_line(dt, gid, host)
        td.add_filterlog(dt_range, gid, host, stat, val)
        td.commit()
        del td

        fl = FilterLog(dt_range, gid, host, stat, val)
        _logger.debug(str(fl))


def apply_filter(conf, ld, l_dt, dt_range, evdef):
    """Apply filter fucntions for time-series based on given configuration.
    
    Args:
        conf (configparser.ConfigParser)
        ld (amulog.log_db.LogData)
        l_dt (List[datetime.datetime])
        dt_range (datetime.datetime, datetime.datetime)
        evdef (int, str): tuple of gid and host.

    Returns:
        stat (str): 1 of ["none", "const", "period"]
        l_dt (List[datetime.datetime]): time series after filtering
        val (int): optional value that explain filtering status.
                   periodicity interval if stat is "period"
                   time-series counts per a day if stat is "const"
    """
    usefilter = conf.getboolean("database_ts", "usefilter")
    if usefilter:
        act = conf.get("filter", "action")
        if act in ("remove", "replace"):
            pflag, remain, interval = filter_periodic(conf, ld, l_dt, dt_range,
                                                      evdef, method = method)
            if pflag:
                return ("period", remain, int(interval))
            else:
                return ("none", l_dt, None)
        elif act == "linear":
            lflag = filter_linear(conf, l_dt, dt_range)
            if lflag:
                return ("const", None, len(l_dt))
            else:
                return ("none", l_dt, None)
        elif act in ("remove+linear", "replace+linear"):
            method = act.partition("+")[0]
            # periodic
            pflag, remain, interval = filter_periodic(conf, ld, l_dt, dt_range,
                                                      evdef, method = method)
            if pflag:
                return ("period", remain, int(interval))
            # linear
            lflag = filter_linear(conf, l_dt, dt_range)
            if lflag:
                return ("const", None, len(l_dt))
            else:
                return ("none", l_dt, None)
        elif act in ("linear+remove", "linear+replace"):
            method = act.partition("+")[-1]
            # linear
            lflag = filter_linear(conf, l_dt, dt_range)
            if lflag:
                return ("const", None, len(l_dt))
            # periodic
            pflag, remain, interval = filter_periodic(conf, ld, l_dt,
                                                      dt_range, evdef,
                                                      method = method)
            if pflag:
                return ("period", remain, int(interval))
            else:
                return ("none", l_dt, None)
        else:
            raise NotImplementedError
    else:
        return ("none", l_dt, None)


def filter_linear(conf, l_dt, dt_range):
    """Return True if a_cnt appear linearly."""
    binsize = config.getdur(conf, "filter", "linear_binsize")
    threshold = conf.getfloat("filter", "linear_threshold")
    th_count = conf.getint("filter", "linear_count")

    if len(l_dt) < th_count:
        return False

    # generate time-series cumulative sum
    length = (dt_range[1] - dt_range[0]).total_seconds()
    bin_length = binsize.total_seconds()
    bins = math.ceil(1.0 * length / bin_length)
    a_stat = np.array([0] * int(bins))
    for dt in l_dt:
        cnt = int((dt - dt_range[0]).total_seconds() / bin_length)
        assert cnt < len(a_stat)
        a_stat[cnt:] += 1

    a_linear = np.linspace(0, len(l_dt), bins, endpoint = False)
    val = sum((a_stat - a_linear) ** 2) / (bins * len(l_dt))
    return val < threshold


def filter_periodic(conf, ld, l_dt, dt_range, evdef, method):
    """Return True and the interval if a_cnt is periodic."""

    ret_false = False, None, None
    gid_name = conf.get("dag", "event_gid")
    p_cnt = conf.getint("filter", "pre_count")
    p_term = config.getdur(conf, "filter", "pre_term")
    
    # preliminary test
    if len(l_dt) < p_cnt:
        _logger.debug("time-series count too small, skip")
        return ret_false
    elif max(l_dt) - min(l_dt) < p_term:
        _logger.debug("time-series range too small, skip")
        return ret_false

    # periodicity test
    for dt_cond in config.gettuple(conf, "filter", "sample_rule"):
        dt_length, binsize = [config.str2dur(s) for s in dt_cond.split("_")]
        if (dt_range[1] - dt_range[0]) == dt_length:
            temp_l_dt = l_dt
        else:
            temp_l_dt = reload_ts(ld, evdef, dt_length, dt_range, gid_name)
        a_cnt = dtutil.discretize_sequential(temp_l_dt, dt_range,
                                             binsize, binarize = False)

        remain_dt = None
        if method == "remove":
            flag, interval = period.fourier_remove(conf, a_cnt, binsize)
        elif method == "replace":
            flag, remain_array, interval = period.fourier_replace(conf, a_cnt,
                                                                  binsize)
            if remain_array is not None:
                remain_dt = revert_event(remain_array, dt_range, binsize)
        elif method == "corr":
            flag, interval = period.periodic_corr(conf, a_cnt, binsize) 
        else:
            raise NotImplementedError
        if flag:
            return flag, remain_dt, interval
    return ret_false


def reload_ts(ld, evdef, dt_length, dt_range, gid_name):
    new_top_dt = dt_range[1] - dt_length
    d = {gid_name: evdef[0],
         "host": evdef[1],
         "top_dt": new_top_dt,
         "end_dt": dt_range[1]}
    iterobj = ld.iter_lines(**d)
    return [line.dt for line in iterobj]


def revert_event(a_cnt, dt_range, binsize):
    top_dt, end_dt = dt_range
    assert top_dt + len(a_cnt) * binsize == end_dt
    return [top_dt + i * binsize for i, val in enumerate(a_cnt) if val > 0]


