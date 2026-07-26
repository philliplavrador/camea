import { describe, it, expect } from 'vitest';
import { normalisePath, splitPath, forSubmit, shortPath } from './pathText';

describe('normalisePath — what a human actually pastes', () => {
  it('turns Windows backslashes into forward slashes', () => {
    expect(normalisePath('D:\\Projects\\Camea\\data')).toBe('D:/Projects/Camea/data');
  });

  it("strips Explorer's Copy-as-path quotes", () => {
    expect(normalisePath('"D:\\Projects\\Camea\\data"')).toBe('D:/Projects/Camea/data');
    expect(normalisePath("'/mnt/data'")).toBe('/mnt/data');
  });

  it('trims surrounding whitespace and collapses doubled separators', () => {
    expect(normalisePath('  D:\\\\Projects//Camea  ')).toBe('D:/Projects/Camea');
  });

  it('keeps a UNC share double slash', () => {
    expect(normalisePath('\\\\server\\share\\runs')).toBe('//server/share/runs');
  });
});

describe('splitPath — the folder to list vs the fragment to match', () => {
  it('splits at the last separator', () => {
    expect(splitPath('D:/Projects/Cam')).toEqual({ dir: 'D:/Projects/', frag: 'Cam' });
  });

  it('leaves an empty dir when nothing has been typed yet (the drive list)', () => {
    expect(splitPath('D')).toEqual({ dir: '', frag: 'D' });
  });

  it('gives an empty fragment right after a separator', () => {
    expect(splitPath('D:/Projects/')).toEqual({ dir: 'D:/Projects/', frag: '' });
  });
});

describe('shortPath — a chip label that stays distinguishable', () => {
  it('leaves a short path alone', () => {
    expect(shortPath('D:/data')).toBe('D:/data');
  });

  it('elides the HEAD, so two deep siblings do not read the same', () => {
    const a = shortPath('D:/Projects/Camea/data/drive/260620/260620_Imaging/260620a');
    const b = shortPath('D:/Projects/Camea/data/drive/260620/260620_Imaging/260620d');
    expect(a).toBe('…/260620_Imaging/260620a');
    expect(b).toBe('…/260620_Imaging/260620d');
    expect(a).not.toBe(b);
  });

  it('falls back to the last segment when two would still overflow', () => {
    expect(shortPath('/a/an-extremely-long-directory-name/final-leaf-folder', 24)).toBe(
      '…/final-leaf-folder',
    );
  });
});

describe('forSubmit — the path the scanner gets', () => {
  it('drops a trailing separator', () => {
    expect(forSubmit('D:/Projects/Camea/')).toBe('D:/Projects/Camea');
  });

  it('keeps the separator on a drive root, where it IS the path', () => {
    expect(forSubmit('D:/')).toBe('D:/');
  });

  it('normalises on the way through', () => {
    expect(forSubmit(' "D:\\Projects\\Camea\\" ')).toBe('D:/Projects/Camea');
  });
});
