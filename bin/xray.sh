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

source ${this}/../config.sh || { echo "source config.sh failed"; exit 1; }

firewallCMD=iptables
beginCron="#begin v2relay cron"
endCron="#end v2relay cron"
defaultXrayPath="${appsDir}/xray/xray"

add(){
    local name=${1:?'missing name'}

    # check existence
    # echo "${etcDir}"
    # echo ${appsDir}
    echo "+ Check ${name} existence..."
    if [ -e ${etcDir}/${name}.yaml ];then
        echo "${RED}Error: ${name} already exists${NORMAL}"
        exit 1
    fi
    echo "+ No ${name},create it..."

    # copy and edit config.yaml
    cp ${appsDir}/genfrontend/config.yaml ${etcDir}/${name}.yaml
    $ed ${etcDir}/${name}.yaml
    _genServiceFile ${name}
}

_genServiceFile(){
    local name=${1:?'missing config name'}
    # genfrontend ${name}.json
    echo "+ Generate ${name}.json from ${name}.yaml"
    _run "(${appsDir}/genfrontend/genfrontend -t ${appsDir}/genfrontend/frontendTemplate -c ${etcDir}/${name}.yaml -o ${etcDir}/${name}.json)" || { echo "${RED}failed!"; exit 1; }

    local start_pre="${binDir}/xray.sh _start_pre ${name}"
    # local start="${appsDir}/xray/xray run -c ${etcDir}/${name}.json"
    local start="${binDir}/xray.sh _start ${name}"
    local start_post="${binDir}/xray.sh _start_post ${name}"
    local stop_post="${binDir}/xray.sh _stop_post ${name}"
    local user="${xrayUser:-clash}"
    local group="${xrayGroup:-clash}"
    local pwd="${appsDir}/xray"
    local xrayPath=${appsDir}/xray/xray

    # add $user to sudo nopass file
    nopassFile="/etc/sudoers.d/nopass"
    if [ ! -e "${nopassFile}" ];then
        _runAsRoot "touch ${nopassFile}"
    fi
    if ! grep -q "${user} ALL=(ALL:ALL) NOPASSWD:ALL" "${nopassFile}";then
        _runAsRoot "echo \"${user} ALL=(ALL:ALL) NOPASSWD:ALL\" >>${nopassFile}"
    fi

    # new systemd servie file
    sed -e "s|<START_PRE>|${start_pre}|g" \
        -e "s|<START>|${start}|g" \
        -e "s|<START_POST>|${start_post}|g" \
        -e "s|<STOP_POST>|${stop_post}|g" \
        -e "s|<USER>|${user}|g" \
        -e "s|<GROUP>|${group}|g" \
        -e "s|<PWD>|${pwd}|g" \
        -e "s|<XRAY_PATH>|${xrayPath}|g" \
        ${templateDir}/xray.service > /tmp/xray-${name}.service

    _runAsRoot "mv /tmp/xray-${name}.service /etc/systemd/system"
    _runAsRoot "systemctl daemon-reload"
    # _runAsRoot "sudo systemctl enable xray-${name}.service"
    # _runAsRoot "sudo systemctl restart xray-${name}.service"
}

list(){
    (cd ${etcDir} && find . -iname "*.yaml" -printf "%P\n")
}

config(){
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configFile="${etcDir}/${configName%.yaml}.yaml"
    if [ ! -e "${configFile}" ];then
        echo "${RED}Error: no such config${NORMAL}"
        exit 1
    fi

    local pre="$(stat ${configFile} | grep Modify)"
    ${ed} "${configFile}"
    local post="$(stat ${configFile} | grep Modify)"

    if [ "${pre}" != "${post}" ];then
        echo "Config file changed,generate new config and restart service..."
        start ${configName}
    fi
}

start(){
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    _genServiceFile $configName
    _runAsRoot "systemctl start xray-${configName}.service"
}

_start(){
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"

    if [ -n "${XRAY_PATH}" ];then
        xrayPath="${XRAY_PATH}"
    else
        xrayPath="${defaultXrayPath}"
    fi
    echo "xrayPath: ${xrayPath}"
    "${xrayPath}" run -c "${etcDir}/${configName}.json"
}

stop(){
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    _runAsRoot "systemctl stop xray-${configName}.service"
}

restart(){
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    stop ${configName}
    start ${configName}
}

_start_pre(){
    echo "Enter _start_pre()..."
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    # check xray genfrontend
    if [ ! -e ${appsDir}/xray/xray ];then
        echo "Error: no xray found!"
        exit 1
    fi

    if [ ! -e ${appsDir}/genfrontend/genfrontend ];then
        echo "Error: no genfrontend found!"
        exit 1
    fi

    # check config file(json)
    if [ ! -e "${etcDir}/${configName}.json" ];then
        echo "No ${configName}.json found!"
        exit 1
    fi
}

_start_post(){
    echo "Enter _start_post()..."
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    #traffic,cron
    bash ${scriptsDir}/traffic.sh _addWatchPorts ${configName}
    _addCron ${configName}
}

_stop_post(){
    echo "Enter _stop_post()..."
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    #traffic,cron
    bash ${scriptsDir}/traffic.sh _delWatchPorts ${configName}
    _delCron ${configName}
}

_addCron() {
    echo "Enter _addCron()..."
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    local tmpCron=/tmp/cron.tmp$(date +%FT%T)
    if crontab -l 2>/dev/null | grep -q "${beginCron}-${configName}"; then
        echo "Already exist,quit."
        return 0
    fi
    cat >${tmpCron} <<-EOF
	${beginCron}-${configName}
	# NOTE!! saveHour saveDay need run iptables with sudo,
	# so make sure you can run iptables with sudo no passwd
	# or you are root
	0 * * * * ${binDir}/xray.sh traffic saveHour ${configName}
	59 23 * * * ${binDir}/xray.sh traffic saveDay ${configName}
	${endCron}-${configName}
	EOF

    ( crontab -l 2>/dev/null; cat ${tmpCron}) | sudo crontab -
}

_delCron() {
    echo "Enter _delCron()..."
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    (crontab -l 2>/dev/null | sed -e "/${beginCron}-${configName}/,/${endCron}-${configName}/d") | sudo crontab -
}

traffic(){
    bash ${scriptsDir}/traffic.sh "$@"
}

remove(){
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    if [ ! -e "${etcDir}/${configName}.json" ];then
        echo "${RED}Error: No ${configName} service found!${NORMAL}"
        exit 1
    fi
    echo "Remove ${configName}..."
    _runAsRoot "systemctl stop xray-${configName}.service"
    _runAsRoot "/bin/rm -rf /etc/systemd/system/xray-${configName}.service"
    _run "/bin/rm -rf ${etcDir}/${configName}.yaml"
    _run "/bin/rm -rf ${etcDir}/${configName}.json"
}

_removeAll(){
    cd ${etcDir}
    for etc in $(ls *.yaml 2>/dev/null);do
        remove ${etc%.yaml}
        _run "/bin/rm -rf ${etc%.yaml}.json"
        _run "/bin/rm -rf ${etc}"
    done
}

em(){
    $ed $0
}

###############################################################################
# write your code above
###############################################################################
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
