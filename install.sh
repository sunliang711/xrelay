#!/bin/bash
if [ -z "${BASH_SOURCE}" ]; then
    this=${PWD}
else
    rpath="$(readlink ${BASH_SOURCE})"
    if [ -z "$rpath" ]; then
        rpath=${BASH_SOURCE}
    elif echo "$rpath" | grep -q '^/'; then
        # absolute path
        echo
    else
        # relative path
        rpath="$(dirname ${BASH_SOURCE})/$rpath"
    fi
    this="$(cd $(dirname $rpath) && pwd)"
fi

if [ -r ${SHELLRC_ROOT}/shellrc.d/shelllib ];then
    source ${SHELLRC_ROOT}/shellrc.d/shelllib
elif [ -r /tmp/shelllib ];then
    source /tmp/shelllib
else
    # download shelllib then source
    shelllibURL=https://gitee.com/sunliang711/init2/raw/master/shell/shellrc.d/shelllib
    (cd /tmp && curl -s -LO ${shelllibURL})
    if [ -r /tmp/shelllib ];then
        source /tmp/shelllib
    fi
fi

# available VARs: user, home, rootID
# available functions: 
#    _err(): print "$*" to stderror
#    _command_exists(): check command "$1" existence
#    _require_command(): exit when command "$1" not exist
#    _runAsRoot():
#                  -x (trace)
#                  -s (run in subshell)
#                  --nostdout (discard stdout)
#                  --nostderr (discard stderr)
#    _insert_path(): insert "$1" to PATH
#    _run():
#                  -x (trace)
#                  -s (run in subshell)
#                  --nostdout (discard stdout)
#                  --nostderr (discard stderr)
#    _ensureDir(): mkdir if $@ not exist
#    _root(): check if it is run as root
#    _require_root(): exit when not run as root
#    _linux(): check if it is on Linux
#    _require_linux(): exit when not on Linux
#    _wait(): wait $i seconds in script
#    _must_ok(): exit when $? not zero
#    _info(): info log
#    _infoln(): info log with \n
#    _error(): error log
#    _errorln(): error log with \n
#    _checkService(): check $1 exist in systemd


###############################################################################
# write your code below (just define function[s])
# function is hidden when begin with '_'
###############################################################################
source ${this}/config.sh || { echo "source config.sh failed"; exit 1; }
clashUser=clash

_need(){
    local cmd=${1}
    if ! command -v $cmd >/dev/null 2>&1;then
        echo "need $cmd"
        exit 1
    fi
}

install() {
    _run "mkdir ${root}/etc"
    _run "${scriptsDir}/installXray.sh install ${root}/apps" || { echo "Install xray failed!"; exit 1; }
    _run "${scriptsDir}/installGenfrontend.sh install ${root}/apps" || { echo "Install genfrontend failed!"; exit 1; }
    _insert_path "${binDir}"
    _createUser
    _installIptables
    echo "Add ${binDir} to PATH"
}

_installIptables(){
    if ! command -v iptables>/dev/null 2>&1;then
        echo "install iptables.."
        sudo apt install iptables -y || { echo "failed!"; exit 1; }
    fi

}

_createUser(){
    if [ $(uname) != "Linux" ];then
        return
    fi
    if id -u ${clashUser} >/dev/null 2>&1;then
        echo "user: ${clashUser} exists"
        return
    fi
    echo "add user: ${clashUser}.."
    sudo useradd -M -U -s /sbin/nologin ${clashUser} || { echo "add user: ${clashUser} failed!"; return 1; }
}

uninstall() {
    echo "Remove genfrontend..."
    _run "/bin/rm -rf ${appsDir}/genfrontend"

    echo "Remove xray..."
    _run "/bin/rm -rf ${appsDir}/xray"

    # TODO
    # stop all service and remove all service files
    ${binDir}/xray.sh _removeAll
}

em() {
    $ed $0
}

###############################################################################
# write your code above
###############################################################################
function _help() {
    cd ${this}
    cat <<EOF2
Usage: $(basename $0) ${bold}CMD${reset}

${bold}CMD${reset}:
EOF2
    perl -lne 'print "\t$2" if /^\s*(function)?\s*(\w+)\(\)\s*\{$/' $(basename ${BASH_SOURCE}) | perl -lne "print if /^\t[^_]/"
}

case "$1" in
"" | -h | --help | help)
    _help
    ;;
*)
    "$@"
    ;;
esac
