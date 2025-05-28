" This .vimrc is intended to be used when bundled by PyInstaller.

" When Vim starts, this file is sourced.
" <sfile> refers to this .vimrc file itself.
" :p gives its full path, :h gives its head (directory).
let s:bundle_config_dir = expand('<sfile>:p:h')

" Path to the bundled Vim runtime (e.g., MEIPASS/config/vim_runtime)
let s:vim_runtime_dir = s:bundle_config_dir . '/vim_runtime'

" Path to the bundled fzf plugin and its runtime files (e.g., MEIPASS/config/fzf_vim_plugin)
" This directory will contain:
" - plugin/fzf.vim (the main plugin file)
" - fzf/autoload/fzf.vim (runtime files for fzf)
" - fzf/plugin/fzf.vim (runtime files for fzf)
let s:fzf_plugin_base_dir = s:bundle_config_dir . '/fzf_vim_plugin'

" Prepend these paths to Vim's runtimepath.
" Order can be important. Usually, user-specific/plugin paths come before system paths.
" However, for a bundled app, we want our bundled Vim runtime to be primary.

" Add Vim's own bundled runtime first, then fzf specific things.
" Vim will search these paths for 'plugin/', 'autoload/', 'doc/', etc.
execute 'set runtimepath^=' . fnameescape(s:vim_runtime_dir)
execute 'set runtimepath+=' . fnameescape(s:fzf_plugin_base_dir) " Add fzf plugin files
execute 'set runtimepath+=' . fnameescape(s:fzf_plugin_base_dir . '/fzf') " Add fzf's own runtime files

" Your F2 mapping
nnoremap <silent> <F2> :Lines<CR>

" Optional: Add some debugging to see if paths are set correctly when Vim starts
" echom "Bundled .vimrc loaded."
" echom "Vim runtime path: " . s:vim_runtime_dir
" echom "fzf plugin base path: " . s:fzf_plugin_base_dir
" echom "Complete Runtimepath: " . &runtimepath
" echom "Effective fzf#run: " . exists('*fzf#run') 