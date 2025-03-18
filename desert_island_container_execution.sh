#!/bin/bash
#
# Run TCP server code you don't trust in a container that allows your host to access it
# (connecting to localhost/port fwds to the container) but the container can't access
# things outside the LAN)
#
PORT=${1:-8013}
IMAGE=${2:-debian}
(
    sleep 2
    CONTAINER_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' desert_island)
    echo -e "\r\n[-] Container runs at IP: ${CONTAINER_IP}\r"
    if [ -n "$CONTAINER_IP" ] ; then
        echo -e "[-] Updating iptables...\r"
        sudo iptables -I DOCKER-USER -p tcp -d "$CONTAINER_IP" --dport "$PORT" -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
        sudo iptables -I DOCKER-USER -s "$CONTAINER_IP" -j DROP
        echo -e "$CONTAINER_IP" > /dev/shm/desert_island.ip
        echo -e "[-] Press ENTER to use the container now.\r"
    fi
) &
docker run --name desert_island -p 127.0.0.1:"$PORT":"$PORT" --rm -v "$PWD":/work -u 1000 -it "$IMAGE" /bin/bash
CONTAINER_IP=$(cat /dev/shm/desert_island.ip)
echo "[-] Container at IP ${CONTAINER_IP} stops now."
echo "[-] Reseting iptables..."
sudo iptables -D DOCKER-USER -p tcp -d "$CONTAINER_IP" --dport "$PORT" -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
sudo iptables -D DOCKER-USER -s "$CONTAINER_IP" -j DROP
echo "[-] Done."
