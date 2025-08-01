set nocompatible " Enable Vim's modern features; MUST be the first line

" Get plugin directories from environment variables set by KubeZen
let s:fzf_base_dir_env    = $KUBEZEN_FZF_BASE_PLUGIN_DIR
let s:fzf_plugin_dir_env  = $KUBEZEN_FZF_VIM_COMMANDS_PLUGIN_DIR
let s:fzf_bin_dir_env     = $KUBEZEN_FZF_VIM_COMMANDS_BIN_DIR

" Determine KubeZen root for fallback (works for bundle and dev)
" <sfile>:p:h is assets/runtime_config, then :h to assets, :h to root.
let s:kubezen_root_fallback = expand('<sfile>:p:h:h:h')

" Fallback if environment variables are not set (e.g., direct vim -u app.vimrc usage)
if empty(s:fzf_base_dir_env)
  let s:fzf_base_dir = s:kubezen_root_fallback . '/assets/fzf_base_plugin'
  echom "KUBEZEN_FZF_BASE_PLUGIN_DIR not set, using fallback: " . s:fzf_base_dir
else
  let s:fzf_base_dir = s:fzf_base_dir_env
endif

if empty(s:fzf_plugin_dir_env)
  let s:fzf_plugin_dir = s:kubezen_root_fallback . '/assets/fzf_vim_plugin'
  echom "KUBEZEN_FZF_VIM_COMMANDS_PLUGIN_DIR not set, using fallback: " . s:fzf_plugin_dir
else
  let s:fzf_plugin_dir = s:fzf_plugin_dir_env
endif

if empty(s:fzf_bin_dir_env)
  let s:fzf_bin_dir = s:kubezen_root_fallback . '/bin' " Expect fzf executable in KubeZen_Root/bin
  echom "KUBEZEN_FZF_VIM_COMMANDS_BIN_DIR not set, using fallback for fzf binary dir: " . s:fzf_bin_dir
else
  let s:fzf_bin_dir = s:fzf_bin_dir_env
endif

" Preserve KubeZen's vim_runtime if needed, or remove if all plugins are handled by KUBEZEN_ vars.
" For now, assume s:vim_runtime_dir is still valid as it wasn't part of the KUBEZEN_FZF env vars.
let s:vim_runtime_dir = expand('<sfile>:p:h') . '/vim_runtime' 

" Prepend runtime paths so their plugin/*.vim files are sourced early
if !empty(s:fzf_plugin_dir) && isdirectory(s:fzf_plugin_dir)
  execute 'set runtimepath^=' . fnameescape(s:fzf_plugin_dir)
else
  echom "Warning: FZF commands plugin directory is empty or not a directory: " . s:fzf_plugin_dir
endif

if !empty(s:fzf_base_dir) && isdirectory(s:fzf_base_dir)
  execute 'set runtimepath^=' . fnameescape(s:fzf_base_dir)
else
  echom "Warning: FZF base plugin directory is empty or not a directory: " . s:fzf_base_dir
endif

if !empty(s:vim_runtime_dir) && isdirectory(s:vim_runtime_dir) " Keep existing vim_runtime path for now
  execute 'set runtimepath^=' . fnameescape(s:vim_runtime_dir)
endif

let g:fzf_blines_options = '--bind "f3:abort"'

" Keybinding: Use F2 to open the :BLines search.
" It will automatically pick up the options defined above.
nnoremap <F3> :BLines<CR>

" --- Quality of Life Mappings ---

" Save and Exit with Ctrl+S in normal and insert mode
nnoremap <C-s> :wq<CR>
inoremap <C-s> <C-o>:wq<CR>

" Quit with <leader>q (e.g., \q)
nnoremap <leader>q :q<CR>

" Force Quit with <leader>Q (e.g., \Q)
nnoremap <leader>Q :q!<CR>

" Exit without saving (force quit) with Ctrl+X
nnoremap <C-x> :q!<CR>
inoremap <C-x> <C-o>:q!<CR>
