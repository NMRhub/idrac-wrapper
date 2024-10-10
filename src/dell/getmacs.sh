#!/bin/bash
ORIGIN=$(dirname $(readlink -f $0))
if [ $# -lt 1 ]; then
	echo "Usage: $0 [password in file]" 
	exit 1
fi
NIC=NIC.Integrated.1-1-1
NAMES=()
for ((i=1;i<=1;i++)); do
	NAMES+=("matlab$i.nmrbox.org")
done
PWD=`cat $1`
for name in "${NAMES[@]}"; do
	ip=$(dig +short $name)
	idrac="idrac-$name"
	st=$(idrac $idrac --summary | awk '{print $3 " " $4}')
	mac=$(python3 GetEthernetInterfacesREDFISH.py -ip $idrac -u root -p  $PWD --get $NIC |grep PermanentMACAddress)
	echo "$name $st $ip $mac"
done

