#!/bin/bash
if [ -z "${BASH_SOURCE}" ]; then
    this=${PWD}
    logfile="/tmp/$(%FT%T).log"
else
    rpath="$(readlink ${BASH_SOURCE})"
    if [ -z "$rpath" ]; then
        rpath=${BASH_SOURCE}
    fi
    this="$(cd $(dirname $rpath) && pwd)"
    logfile="/tmp/$(basename ${BASH_SOURCE}).log"
fi

source ${this}/../config.sh || { echo "Source config.sh failed"; exit 1; }

export PATH=$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

user="${SUDO_USER:-$(whoami)}"
home="$(eval echo ~$user)"

# export TERM=xterm-256color

# Use colors, but only if connected to a terminal, and that terminal
# supports them.
if which tput >/dev/null 2>&1; then
  ncolors=$(tput colors 2>/dev/null)
fi
if [ -t 1 ] && [ -n "$ncolors" ] && [ "$ncolors" -ge 8 ]; then
    RED="$(tput setaf 1)"
    GREEN="$(tput setaf 2)"
    YELLOW="$(tput setaf 3)"
    BLUE="$(tput setaf 4)"
    CYAN="$(tput setaf 5)"
    BOLD="$(tput bold)"
    NORMAL="$(tput sgr0)"
else
    RED=""
    GREEN=""
    YELLOW=""
    CYAN=""
    BLUE=""
    BOLD=""
    NORMAL=""
fi

_err(){
    echo "$*" >&2
}

_command_exists(){
    command -v "$@" > /dev/null 2>&1
}

rootID=0

_runAsRoot(){
    cmd="${*}"
    bash_c='bash -c'
    if [ "${EUID}" -ne "${rootID}" ];then
        if _command_exists sudo; then
            bash_c='sudo -E bash -c'
        elif _command_exists su; then
            bash_c='su -c'
        else
            cat >&2 <<-'EOF'
			Error: this installer needs the ability to run commands as root.
			We are unable to find either "sudo" or "su" available to make this happen.
			EOF
            exit 1
        fi
    fi
    # only output stderr
    (set -x; $bash_c "${cmd}" >> ${logfile} )
}

_run(){
    # only output stderr
    cmd="${*}"
    (set -x; bash -c "${cmd}" >> ${logfile})
}

function _root(){
    if [ ${EUID} -ne ${rootID} ];then
        echo "${RED}Requires root privilege.${NORMAL}"
        exit 1
    fi
}

ed=vi
if _command_exists vim; then
    ed=vim
fi
if _command_exists nvim; then
    ed=nvim
fi
# use ENV: editor to override
if [ -n "${editor}" ];then
    ed=${editor}
fi

_need(){
    local cmd=${1}
    if ! _command_exists "${cmd}";then
        _err "${RED}Need command ${cmd}${NORMAL}"
        exit 1
    fi
}

install(){
    _need curl
    _need unzip
    echo "Log file: ${logfile}"

    local dest=${1:?'missing install location'}

    # print msg
    echo "${GREEN}"
    cat ${this}/xray_msg
    echo "${NORMAL}"
    echo 

    if [ ! -d ${dest} ];then
        echo "Create ${dest}..."
        (set -x; mkdir -p ${dest})
    fi
    dest="$(cd ${dest} && pwd)"
    if [ -d "${dest}/xray" ];then
        echo "${YELLOW}xray executable already installed in ${dest}/xray,skip${NORMAL}"
        exit
    fi
    echo "Install location: $dest"

    version=${2:-1.2.4}

    downloadDir=/tmp/xray-download
    echo "Download dir: $downloadDir"
    if [ ! -d "$downloadDir" ];then
        mkdir "$downloadDir"
    fi
    cd "$downloadDir"

    case $(uname) in
        Darwin)
            url="https://source711.oss-cn-shanghai.aliyuncs.com/xray/${version}/Xray-macos-64.zip"
            zipfile=${url##*/}
            ;;
        Linux)
            url="https://source711.oss-cn-shanghai.aliyuncs.com/xray/${version}/Xray-linux-64.zip"
            zipfile=${url##*/}
            ;;
    esac

    # rasperberry arm64
    if [ $(uname -m) == "aarch64" ];then
        url="https://source711.oss-cn-shanghai.aliyuncs.com/xray/${version}/Xray-linux-arm64-v8a.zip"
        zipfile=${url##*/}
    fi

    if [ ! -e "$zipfile" ];then
        curl -LO "$url" || { echo "download $zipfile error"; exit 1; }
    else
        echo "Use ${downloadDir}/$zipfile cache file"
    fi

    echo -n "Unzip zipfile: $zipfile..."
    unzip -d "$dest/xray" "$zipfile" >/dev/null && { echo "OK"; } || { echo "Extract xray zip file error"; exit 1; }
    chmod +x ${dest}/xray/xray

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

