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

function _insert_path(){
    if [ -z "$1" ];then
        return
    fi
    echo -e ${PATH//:/"\n"} | grep -c "^$1$" >/dev/null 2>&1 || export PATH=$1:$PATH
}

_run(){
    # only output stderr
    cmd="${*}"
    (set -x; bash -c "${cmd}" >> ${logfile})
}

function _root(){
    if [ ${EUID} -ne ${rootID} ];then
        echo "Requires root privilege."
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
###############################################################################
# write your code below (just define function[s])
# function is hidden when begin with '_'
###############################################################################
firewallCMD=iptables
beginCron="#begin v2relay cron"
endCron="#end v2relay cron"

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
    _new ${name}
}

_new(){
    local name=${1:?'missing config name'}
    # genfrontend ${name}.json
    echo "+ Generate ${name}.json from ${name}.yaml"
    _run "(${appsDir}/genfrontend/genfrontend -t ${appsDir}/genfrontend/frontendTemplate -c ${etcDir}/${name}.yaml -o ${etcDir}/${name}.json)" || { echo "${RED}failed!"; exit 1; }

    local start_pre="${binDir}/xray.sh _start_pre ${name}"
    local start="${appsDir}/xray/xray run -c ${etcDir}/${name}.json"
    local start_post="${binDir}/xray.sh _start_post ${name}"
    local stop_post="${binDir}/xray.sh _stop_post ${name}"
    local user="root"
    local pwd="${appsDir}/xray"

    # new systemd servie file
    sed -e "s|<START_PRE>|${start_pre}|g" \
        -e "s|<START>|${start}|g" \
        -e "s|<START_POST>|${start_post}|g" \
        -e "s|<STOP_POST>|${stop_post}|g" \
        -e "s|<USER>|${user}|g" \
        -e "s|<PWD>|${pwd}|g" \
        ${templateDir}/xray.service > /tmp/xray-${name}.service

    _runAsRoot "mv /tmp/xray-${name}.service /etc/systemd/system"
    _runAsRoot "sudo systemctl daemon-reload"
    _runAsRoot "sudo systemctl enable xray-${name}.service"
    _runAsRoot "sudo systemctl restart xray-${name}.service"
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
        _new ${configName}
    fi
}

start(){
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    configName="${configName%.yaml}"
    _runAsRoot "systemctl start xray-${configName}.service"
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

    ( crontab -l 2>/dev/null; cat ${tmpCron}) | crontab -
}

_delCron() {
    echo "Enter _delCron()..."
    local configName=${1:?'missing config file name (just name,no yaml extension)'}
    (crontab -l 2>/dev/null | sed -e "/${beginCron}-${configName}/,/${endCron}-${configName}/d") | crontab -
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
    _runAsRoot "/bin/rm -rf /etc/snystemd/system/xray-${configName}.service"
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
