import Svg, { Path, Rect } from 'react-native-svg';

const paths = {
  search: 'm21 21-4.6-4.6M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0Z',
  top: 'M4 20v-7h4v7M10 20V4h4v16M16 20V9h4v11',
  account: 'M20 21v-2a7 7 0 0 0-14 0v2M17 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  back: 'm15 18-6-6 6-6', close: 'm6 6 12 12M6 18 18 6',
  menu: 'M4 6h16M4 12h16M4 18h16', refresh: 'M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M18 18A8 8 0 0 1 4 12',
} as const;

export function Icon({ name, color = '#95abae', size = 24 }: { name: keyof typeof paths | 'qr'; color?: string; size?: number }) {
  return <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    {name === 'qr' ? <><Rect x={3} y={3} width={6} height={6} rx={1}/><Rect x={15} y={3} width={6} height={6} rx={1}/><Rect x={3} y={15} width={6} height={6} rx={1}/><Path d="M15 15h3v3h3v3h-6v-3M21 15v-1"/></> : <Path d={paths[name]}/>}
  </Svg>;
}
