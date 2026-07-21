/**
 * Shared file utilities — extracted from duplicate definitions
 * in SkillFileBrowser.vue / FilesPage.vue / HermesFilesPage.vue.
 */

import type { Component } from 'vue'
import {
  CodeSlashOutline,
  ImageOutline,
  DocumentTextOutline,
  VideocamOutline,
  MusicalNotesOutline,
  ArchiveOutline,
  DocumentOutline,
} from '@vicons/ionicons5'

export const codeExts = [
  'js', 'jsx', 'ts', 'tsx', 'vue', 'svelte', 'py', 'rb', 'go', 'rs',
  'java', 'kt', 'c', 'cpp', 'h', 'hpp', 'cs', 'swift', 'php', 'sh',
  'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd', 'sql', 'r', 'lua',
  'scala', 'clj', 'hs', 'ml', 'ex', 'exs', 'erl', 'dart', 'toml',
  'yaml', 'yml', 'json', 'xml', 'html', 'css', 'scss', 'less', 'md',
  'dockerfile', 'makefile', 'cmake', 'gradle', 'ini', 'conf', 'env',
  'gitignore', 'editorconfig', 'prettierrc', 'eslintrc',
]

export const imgExts = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp', 'ico', 'tiff', 'avif']

export const pdfExts = ['pdf']

export function getFileIcon(ext: string): Component {
  const extLower = ext.toLowerCase().replace('.', '')
  if (codeExts.includes(extLower)) return CodeSlashOutline
  if (imgExts.includes(extLower)) return ImageOutline
  if (pdfExts.includes(extLower)) return DocumentTextOutline
  const videoExts = ['mp4', 'webm', 'mov', 'avi', 'mkv']
  if (videoExts.includes(extLower)) return VideocamOutline
  const audioExts = ['mp3', 'wav', 'ogg', 'flac', 'aac']
  if (audioExts.includes(extLower)) return MusicalNotesOutline
  const archiveExts = ['zip', 'tar', 'gz', 'rar', '7z']
  if (archiveExts.includes(extLower)) return ArchiveOutline
  return DocumentOutline
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1)
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

export function getAuthHeaders(token: string): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
}
