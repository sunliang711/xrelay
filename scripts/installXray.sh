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


###############################################################################
# write your code below (just define function[s])
# function is hidden when begin with '_'

install(){
    _require_command curl
    _require_command unzip
    _require_command jq

    dest="${1}"
    # download location
    if [ -z "${dest}" ];then
        echo "-- no download destination(\$1), use default location: PWD(${PWD})"
        dest="${PWD}"
    fi
    if [ ! -d "${dest}" ];then
        echo "-- ${dest} not exists, create it.."
        mkdir -p "${dest}" || { echo "create ${dest} failed!"; exit 1; }
    fi

    # download url
    local platform="$(uname)-$(uname -m)"
    case ${platform} in
        Linux-x86_64)
            target="linux-64"
            ;;
        Linux-aarch64)
            target="linux-arm64"
            ;;
        Darwin-x86_64)
            target="macos-64"
            ;;
        Darwin-arm64)
            target="macos-arm64"
            ;;
        *)
            echo "unknown platform"
            exit 1
            ;;
    esac
    version="${2}"
    if [ -n "${version}" ];then
        echo "TODO"
    else
        echo "-- no version specified(\$2), get latest version via github api.."
        # get latest download url
        downloadLink=`curl -s https://api.github.com/repos/XTLS/Xray-core/releases/latest | jq | grep 'browser_download_url' | grep -v 'dgst' | grep "${target}" | head -1 | perl -lne 'print $1 if /"(https.+)"/'`
        if [ -z "${downloadLink}" ];then
            echo "-- cannot get latest download url"
            exit 1
        fi
    fi

    echo "-- download ${downloadLink} to ${dest} .."
    zipFile=${downloadLink##*/}
    (
        cd ${dest}
        echo -n "-- downloading xray.."
        curl -s -LO "${downloadLink}" && { echo " [ok]"; } || { echo "download xray failed!"; exit 1; }
        echo -n "-- unzip xray.."
        unzip "${zipFile}" && { echo " [ok]"; } || { echo "unzip failed!"; exit 1; }

    )


}

# write your code above
###############################################################################

em(){
    $ed $0
}

function _help(){
    cd "${this}"
    cat<<EOF2
Usage: $(basename $0) ${bold}CMD${reset}

${bold}CMD${reset}:
EOF2
    perl -lne 'print "\t$2" if /^\s*(function)?\s*(\S+)\s*\(\)\s*\{$/' $(basename ${BASH_SOURCE}) | perl -lne "print if /^\t[^_]/"
}

case "$1" in
     ""|-h|--help|help)
        _help
        ;;
    *)
        "$@"
esac
