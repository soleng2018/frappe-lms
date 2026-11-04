#!/bin/bash
# Host side proof that the stack survives a restart and a crash (spec 0007, AC-6 and AC-7).
# Run through `make restart-test`, which passes SERVICES (the long running services, one per line).
# Acts only on containers of the nile-lms compose project, found by label.
set -euo pipefail

PROJECT="nile-lms"
KILL_SERVICES=(backend frontend)
TIMEOUT=180
SERVICES="${SERVICES:?SERVICES is blank, run this through make restart-test}"

say() { echo "restart-test: $*"; }
die() {
  echo "restart-test: FAIL $*" >&2
  exit 1
}

# Container ids of one service of this project only.
ids_of() {
  docker ps -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=$1"
}

wait_healthy() {
  local deadline=$((SECONDS + TIMEOUT)) svc id state bad
  while true; do
    bad=""
    for svc in $SERVICES; do
      id="$(ids_of "$svc")"
      if [ -z "$id" ]; then
        bad="$bad $svc(not running)"
        continue
      fi
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no healthcheck{{end}}' "$id")"
      [ "$state" = "healthy" ] || bad="$bad $svc($state)"
    done
    [ -z "$bad" ] && return 0
    if [ "$SECONDS" -ge "$deadline" ]; then die "not healthy after ${TIMEOUT}s:$bad"; fi
    sleep 5
  done
}

say "restarting: ${SERVICES//$'\n'/ }"
for svc in $SERVICES; do
  id="$(ids_of "$svc")"
  [ -n "$id" ] || die "service $svc has no running container in project $PROJECT"
  docker restart "$id" >/dev/null
done
wait_healthy
say "healthy after restart"

# docker kill marks a container as stopped by hand, so unless-stopped would not revive it.
# A kill -9 of the host process looks like a real crash.
declare -A started
for svc in "${KILL_SERVICES[@]}"; do
  id="$(ids_of "$svc")"
  [ -n "$id" ] || die "service $svc has no running container in project $PROJECT"
  started[$svc]="$(docker inspect -f '{{.State.StartedAt}}' "$id")"
  pid="$(docker inspect -f '{{.State.Pid}}' "$id")"
  say "kill -9 $svc (host pid $pid)"
  sudo kill -9 "$pid"
done
for svc in "${KILL_SERVICES[@]}"; do
  deadline=$((SECONDS + TIMEOUT))
  until [ -n "$(ids_of "$svc")" ] &&
    [ "$(docker inspect -f '{{.State.StartedAt}}' "$(ids_of "$svc")")" != "${started[$svc]}" ]; do
    [ "$SECONDS" -lt "$deadline" ] || die "$svc did not come back after the crash within ${TIMEOUT}s"
    sleep 2
  done
done
wait_healthy
say "healthy after crash"

# Live settings must match the compose file (a rebuild could have lost them).
LOG_FMT='{{.HostConfig.LogConfig.Type}} {{index .HostConfig.LogConfig.Config "max-size"}}'
LOG_FMT="$LOG_FMT {{index .HostConfig.LogConfig.Config \"max-file\"}}"
bad=""
for id in $(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT"); do
  name="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")"
  log="$(docker inspect -f "$LOG_FMT" "$id")"
  [ "$log" = "json-file 10m 5" ] || bad="$bad $name(logging: $log)"
done
for svc in $SERVICES; do
  policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$(ids_of "$svc")")"
  [ "$policy" = "unless-stopped" ] || bad="$bad $svc(restart: $policy)"
done
[ -z "$bad" ] || die "live settings differ from the compose file:$bad"
say "logging and restart policy match"

make -s tools CMD="verify deploy"
say "PASS"
