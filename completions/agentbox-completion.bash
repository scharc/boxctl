# Agentbox bash completion
# Usage: source completions/agentbox-completion.bash

_agentbox_completion() {
    local IFS=$'\n'
    local response
    local -a completions

    local cmd="agentbox"
    if ! command -v agentbox >/dev/null 2>&1 && command -v abox >/dev/null 2>&1; then
        cmd="abox"
    fi

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=${COMP_CWORD} _AGENTBOX_COMPLETE=bash_complete "$cmd")

    for line in $response; do
        local type=${line%%$'\t'*}
        local rest=${line#*$'\t'}
        local key=${rest%%$'\t'*}
        if [[ "$type" == "plain" ]]; then
            completions+=("$key")
        elif [[ "$type" == "dir" ]]; then
            COMPREPLY=( $(compgen -d -- "$cur") )
            return 0
        elif [[ "$type" == "file" ]]; then
            COMPREPLY=( $(compgen -f -- "$cur") )
            return 0
        fi
    done

    if [[ ${#completions[@]} -gt 0 ]]; then
        COMPREPLY=( $(compgen -W "${completions[*]}" -- "$cur") )
        return 0
    fi
}

_agentbox_completion_init() {
    local cur
    cur="${COMP_WORDS[COMP_CWORD]}"
    _agentbox_completion
}

complete -F _agentbox_completion_init agentbox
complete -F _agentbox_completion_init abox
