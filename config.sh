#!/bin/bash
if [ -z "${BASH_SOURCE}" ]; then
    root=${PWD}
else
    rpath="$(readlink ${BASH_SOURCE})"
    if [ -z "$rpath" ]; then
        rpath=${BASH_SOURCE}
    fi
    root="$(cd $(dirname $rpath) && pwd)"
fi

scriptsDir=${root}/scripts
templateDir=${root}/template
etcDir=${root}/etc
binDir=${root}/bin
appsDir=${root}/apps
convertDir=${root}/convert
clashGroup=clash