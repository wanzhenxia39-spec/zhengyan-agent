// 线性图标（16px 网格，1.6 描边），颜色跟随 currentColor。
const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const make = (d: React.ReactNode) => (props: React.SVGProps<SVGSVGElement>) => <svg viewBox="0 0 24 24" {...P} {...props}>{d}</svg>;

export const IconChat = make(<path d="M4 5h16v11H9l-5 4z" />);
export const IconHome = make(<><path d="M4 11l8-7 8 7" /><path d="M6 10v10h12V10" /></>);
export const IconFolder = make(<path d="M3 6h7l2 2h9v11H3z" />);
export const IconList = make(<><path d="M8 6h12M8 12h12M8 18h12" /><circle cx="4" cy="6" r=".6" /><circle cx="4" cy="12" r=".6" /><circle cx="4" cy="18" r=".6" /></>);
export const IconChart = make(<><path d="M4 20V4" /><path d="M4 20h16" /><path d="M8 16v-4M12 16V8M16 16v-6" /></>);
export const IconLoop = make(<><path d="M20 12a8 8 0 1 1-2.3-5.6" /><path d="M20 4v5h-5" /></>);
export const IconCpu = make(<><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>);
export const IconPanel = make(<><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></>);
export const IconPanelR = make(<><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M15 4v16" /></>);
export const IconPlus = make(<path d="M12 5v14M5 12h14" />);
export const IconChevron = make(<path d="M9 6l6 6-6 6" />);
export const IconArrowUp = make(<path d="M12 19V5M6 11l6-6 6 6" />);
export const IconArrowRight = make(<path d="M5 12h14M13 6l6 6-6 6" />);
export const IconClose = make(<path d="M6 6l12 12M18 6L6 18" />);
export const IconSun = make(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5" /></>);
export const IconMoon = make(<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />);
export const IconSearch = make(<><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.5-4.5" /></>);
export const IconBell = make(<><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" /><path d="M10 20a2 2 0 0 0 4 0" /></>);
export const IconUser = make(<><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></>);
export const IconFlask = make(<><path d="M9 3h6M10 3v6L5 19a1.5 1.5 0 0 0 1.3 2h11.4a1.5 1.5 0 0 0 1.3-2L14 9V3" /><path d="M7.5 15h9" /></>);
export const IconShield = make(<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />);

export function Sparkle(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" {...props}>
      <defs>
        <linearGradient id="spk" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#9c62df" /><stop offset=".6" stopColor="#d879c2" /><stop offset="1" stopColor="#f2b06f" />
        </linearGradient>
      </defs>
      <path d="M12 1.5c.6 4.8 2.7 7.5 7.8 8.4-5.1.9-7.2 3.6-7.8 8.4-.6-4.8-2.7-7.5-7.8-8.4C9.3 9 11.4 6.3 12 1.5z" fill="url(#spk)" />
      <path d="M19 15.5c.25 1.9 1.1 2.9 3 3.3-1.9.4-2.75 1.4-3 3.3-.25-1.9-1.1-2.9-3-3.3 1.9-.4 2.75-1.4 3-3.3z" fill="url(#spk)" opacity=".7" />
    </svg>
  );
}
