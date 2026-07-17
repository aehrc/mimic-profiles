#!/bin/bash
publisher_jar=publisher.jar
input_cache_path=./input-cache/
txserver=https://velonto.dw.csiro.au/fhir
# velonto's cert chains to the CSIRO internal CA, which Java doesn't trust by
# default; this store = JDK cacerts + that chain (see RUNBOOK.md §8)
tsopts="-Djavax.net.ssl.trustStore=${input_cache_path}velonto-truststore.jks -Djavax.net.ssl.trustStorePassword=changeit"
echo Checking terminology server connection...
curl -sSf "$txserver/metadata" > /dev/null

if [ $? -eq 0 ]; then
	echo "Online ($txserver)"
	txoption="-tx $txserver"
else
	echo "Offline"
	txoption="-tx n/a"
fi

echo "$txoption"

export JAVA_TOOL_OPTIONS="$JAVA_TOOL_OPTIONS -Dfile.encoding=UTF-8"

publisher=$input_cache_path/$publisher_jar
if test -f "$publisher"; then
	java ${JAVA_OPTS:--Xmx10g} $tsopts -jar $publisher -ig . $txoption $*

else
	publisher=../$publisher_jar
	if test -f "$publisher"; then
		java ${JAVA_OPTS:--Xmx10g} $tsopts -jar $publisher -ig . $txoption $*
	else
		echo IG Publisher NOT FOUND in input-cache or parent folder.  Please run _updatePublisher.  Aborting...
	fi
fi
