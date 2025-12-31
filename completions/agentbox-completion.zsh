# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

#compdef agentbox abox

_agentbox_completion() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[agentbox] && ! $+commands[abox] )) && return 1

    local cmd="agentbox"
    if (( ! $+commands[agentbox] )); then
        cmd="abox"
    fi

    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) _AGENTBOX_COMPLETE=zsh_complete "$cmd")}")

    for type key descr in ${response}; do
        if [[ "$type" == "plain" ]]; then
            if [[ "$descr" == "_" ]]; then
                completions+=("$key")
            else
                completions_with_descriptions+=("$key":"$descr")
            fi
        elif [[ "$type" == "dir" ]]; then
            _path_files -/
        elif [[ "$type" == "file" ]]; then
            _path_files -f
        fi
    done

    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi

    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}

if [[ $zsh_eval_context[-1] == loadautofunc ]]; then
    # autoload from fpath, call function directly
    _agentbox_completion "$@"
else
    # eval/source/. command, register function for later
    compdef _agentbox_completion agentbox abox
fi