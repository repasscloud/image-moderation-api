# Shared helpers for the Swoovr Alpine installers. POSIX sh / BusyBox ash only.
# Sourced, never executed directly.

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
info() { printf '%s\n' "$@"; }
heading() { printf '\n== %s ==\n' "$*"; }

require_root() { [ "$(id -u)" -eq 0 ] || die 'Run as root.'; }
require_tty() { [ -t 0 ] || die 'An interactive terminal is required.'; }
require_alpine() { [ -f /etc/alpine-release ] || die 'This installer supports Alpine Linux only.'; }

# --- prompts -----------------------------------------------------------------

# ask VAR "Prompt" [default]
ask() {
    _var=$1 _prompt=$2 _def=${3-}
    if [ -n "$_def" ]; then printf '%s [%s]: ' "$_prompt" "$_def"; else printf '%s: ' "$_prompt"; fi
    IFS= read -r _ans || die 'Input aborted.'
    [ -n "$_ans" ] || _ans=$_def
    eval "$_var=\$_ans"
}

# ask_secret VAR "Prompt"  (input is not echoed)
ask_secret() {
    _var=$1 _prompt=$2
    printf '%s: ' "$_prompt"
    trap 'stty echo; exit 130' INT TERM
    stty -echo
    IFS= read -r _ans || { stty echo; die 'Input aborted.'; }
    stty echo
    trap - INT TERM
    printf '\n'
    eval "$_var=\$_ans"
}

confirm() {
    printf '%s [y/N]: ' "$1"
    IFS= read -r _a || return 1
    case "$_a" in y|Y|yes|YES) return 0;; esac
    return 1
}

# Reject values that would break a single-line KEY=value file.
single_line() {
    case "$1" in *"$(printf '\r')"*) return 1;; esac
    return 0
}

# --- IPv4 --------------------------------------------------------------------

valid_ipv4() {
    case "$1" in ''|*[!0-9.]*|.*|*.|*..*) return 1;; esac
    _old=$IFS; IFS=.
    # shellcheck disable=SC2086
    set -- $1
    IFS=$_old
    [ "$#" -eq 4 ] || return 1
    for _n do
        case "$_n" in 0?*) return 1;; esac   # no leading zeros (would be octal)
        [ "${#_n}" -le 3 ] && [ "$_n" -le 255 ] || return 1
    done
}

is_private_ipv4() {
    case "$1" in
        10.*|192.168.*) return 0;;
        172.*) _o=${1#172.}; _o=${_o%%.*}; [ "$_o" -ge 16 ] && [ "$_o" -le 31 ];;
        *) return 1;;
    esac
}

ipv4_to_int() {
    _old=$IFS; IFS=.
    # shellcheck disable=SC2086
    set -- $1
    IFS=$_old
    echo $(( ($1 << 24) + ($2 << 16) + ($3 << 8) + $4 ))
}

int_to_ipv4() {
    echo "$(( ($1 >> 24) & 255 )).$(( ($1 >> 16) & 255 )).$(( ($1 >> 8) & 255 )).$(( $1 & 255 ))"
}

prefix_mask() {
    [ "$1" -eq 0 ] && { echo 0; return; }
    echo $(( (0xFFFFFFFF << (32 - $1)) & 0xFFFFFFFF ))
}

# cidr_network 10.1.2.3/20 -> 10.1.0.0/20
cidr_network() {
    _ip=${1%/*} _pfx=${1#*/}
    _m=$(prefix_mask "$_pfx")
    echo "$(int_to_ipv4 $(( $(ipv4_to_int "$_ip") & _m )))/$_pfx"
}

# ipv4_in_cidr IP CIDR
ipv4_in_cidr() {
    _net=${2%/*} _pfx=${2#*/}
    _m=$(prefix_mask "$_pfx")
    [ $(( $(ipv4_to_int "$1") & _m )) -eq $(( $(ipv4_to_int "$_net") & _m )) ]
}

# First RFC1918 address assigned to this VM (the likely VPC address).
first_private_ipv4() {
    ip -4 -o addr show scope global 2>/dev/null | awk '{split($4, a, "/"); print a[1]}' |
        while IFS= read -r _ip; do
            if is_private_ipv4 "$_ip"; then echo "$_ip"; break; fi
        done
}

# iface_for_ipv4 IP -> "eth1 10.1.2.3/20"; fails if IP is not local.
iface_for_ipv4() {
    _r=$(ip -4 -o addr show scope global 2>/dev/null | awk -v ip="$1" '
        { split($4, a, "/"); if (a[1] == ip) { print $2, $4; exit } }')
    [ -n "$_r" ] || return 1
    echo "$_r"
}

default_route_iface() {
    ip -4 route show default 2>/dev/null |
        awk '{ for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit } }'
}

# --- config files --------------------------------------------------------------

# conf_get FILE KEY — read KEY=value without sourcing/executing the file.
conf_get() {
    awk -F= -v k="$2" '$1 == k { print substr($0, index($0, "=") + 1); exit }' "$1"
}

ensure_community_repo() {
    if ! grep -Eq '^[^#].*/community/?$' /etc/apk/repositories; then
        _community=$(sed -n '/^[^#].*\/main/ { s@/main@/community@; p; }' /etc/apk/repositories)
        [ -n "$_community" ] || die 'Cannot derive the community repository from /etc/apk/repositories.'
        printf '%s\n' "$_community" >> /etc/apk/repositories
    fi
}
