#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import logging

import yaml
from jinja2 import Environment, FileSystemLoader

# pip3 install pyyaml
# pip3 install jinja2


def setup_log(logfile, log_level):
    LOG_LEVEL = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARN,
        "error": logging.ERROR,
        "fatal": logging.FATAL,
    }
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    DATE_FORMAT = "%Y/%m/%d %H:%M:%S"

    logging.basicConfig(
        filename=logfile,
        level=LOG_LEVEL.get(log_level, logging.ERROR),
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )


class NoInbounds(Exception):
    "Raised when no inbounds in yaml file"

    pass


class InvalidTag(Exception):
    "Raised when tag parts less then 3"

    pass


class NoConfig(Exception):
    "Raised when no config in yaml file"

    pass


SHADOWSOCKS = "shadowsocks"
VMESS = "vmess"
SOCKS5 = "socks5"
HTTP = "http"
OUTBOUND = "outbound"
CONFIG = "config"


def convert(config, template, output):
    with open(config) as configFile:
        data = yaml.safe_load(configFile)
    # add 'port' field
    if "inbounds" not in data:
        raise NoInbounds

    inbounds = data["inbounds"]
    if SHADOWSOCKS in inbounds:
        for s in inbounds[SHADOWSOCKS]:
            parts = s["tag"].split(":")
            if len(parts) < 3:
                raise InvalidTag
            s["port"] = parts[1]

    if VMESS in inbounds:
        for s in inbounds[VMESS]:
            parts = s["tag"].split(":")
            if len(parts) < 3:
                raise InvalidTag
            s["port"] = parts[1]
    if SOCKS5 in inbounds:
        for s in inbounds[SOCKS5]:
            parts = s["tag"].split(":")
            if len(parts) < 3:
                raise InvalidTag
            s["port"] = parts[1]
    if HTTP in inbounds:
        for s in inbounds[HTTP]:
            parts = s["tag"].split(":")
            if len(parts) < 3:
                raise InvalidTag
            s["port"] = parts[1]

    if inbounds[OUTBOUND]["protocol"] == "file":
        filename = inbounds[OUTBOUND]["file"]
        with open(filename) as f:
            inbounds[OUTBOUND]["file"] = f.read()

    # render to template
    env = Environment(loader=FileSystemLoader(searchpath="."))
    tmpl = env.get_template(template)

    if CONFIG not in inbounds:
        raise NoConfig

    # logfile = "/tmp/xray-{}".format(config)
    loglevel = inbounds[CONFIG]["loglevel"]
    log_access = inbounds[CONFIG].get("log_access", "")
    log_error = inbounds[CONFIG].get("log_error", "")
    vmess_port = inbounds[CONFIG].get("vmess_port", 0)
    vmess_network = inbounds[CONFIG].get("vmess_network", "raw")
    api_port = inbounds[CONFIG].get("api_port", 18080)

    # support legacy 'logfile' field falling back to log_access/log_error
    logfile = inbounds[CONFIG].get("logfile", "")

    renderedData = tmpl.render(
        logfile=logfile,
        loglevel=loglevel,
        log_access=log_access,
        log_error=log_error,
        vmess_port=vmess_port,
        vmess_network=vmess_network,
        api_port=api_port,
        shadowsocks=inbounds.get(SHADOWSOCKS, []),
        vmess=inbounds.get(VMESS, []),
        http=inbounds.get(HTTP, []),
        socks5=inbounds.get(SOCKS5, []),
        outbound=inbounds[OUTBOUND],
    )

    with open(output, "w") as outputfile:
        obj = json.loads(renderedData)
        print("output to file: {}".format(output))
        json.dump(obj, outputfile, indent=2)


def main():
    parser = argparse.ArgumentParser(description="yaml file to json file")
    parser.add_argument(
        "--log-level",
        help="log level,default level: warn",
        choices=["debug", "info", "warn", "error", "fatal"],
    )
    parser.add_argument("--log-file", help="log file")

    parser.add_argument("--config", help="config file(yaml)", default="config.yaml")
    parser.add_argument("--template", help="template file", default="tmpl")
    parser.add_argument("--output", help="output json file", default="config.json")
    args = parser.parse_args()

    setup_log(args.log_file, args.log_level)

    # list actions below
    convert(args.config, args.template, args.output)


if __name__ == "__main__":
    main()
