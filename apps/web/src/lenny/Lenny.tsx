// Lenny, ported from the mock's lennySVG(): lit like a soft 3D object, with light from the upper
// left, bounce light from the grass, a glossy highlight, blush and a contact shadow.
import { forwardRef, useId } from 'react'

const BODY =
  'M0,-80 C52,-80 88,-44 88,8 C88,58 52,84 0,84 C-52,84 -88,58 -88,8 C-88,-44 -52,-80 0,-80Z'

function Eye({ cx, u }: { cx: number; u: string }) {
  return (
    <g className="l-lid">
      <ellipse cx={cx} cy={-10} rx={11.5} ry={15.5} fill={`url(#${u}e)`} />
      <ellipse cx={cx + 3.5} cy={-16.5} rx={4.2} ry={5.4} fill="#fff" />
      <circle cx={cx - 3.5} cy={-3} r={2} fill="#fff" opacity={0.75} />
    </g>
  )
}

function Arc({ cx, up }: { cx: number; up: boolean }) {
  return (
    <path
      d={`M${cx - 11},${up ? -6 : -12} Q${cx},${up ? -19 : 0} ${cx + 11},${up ? -6 : -12}`}
      stroke="#101826"
      strokeWidth={4.6}
      fill="none"
      strokeLinecap="round"
    />
  )
}

export const Lenny = forwardRef<SVGSVGElement, { size: 'big' | 'small' | 'preview' }>(
  function Lenny({ size }, ref) {
    const u = 'ln' + useId().replace(/[^a-zA-Z0-9]/g, '')
    return (
      <svg ref={ref} className={`lenny ${size}`} viewBox="-110 -126 220 232" aria-hidden="true">
        <defs>
          <radialGradient id={`${u}b`} cx="36%" cy="28%" r="80%">
            <stop offset="0" style={{ stopColor: 'var(--lb0)' }} />
            <stop offset=".3" style={{ stopColor: 'var(--lb1)' }} />
            <stop offset=".7" style={{ stopColor: 'var(--lb2)' }} />
            <stop offset="1" style={{ stopColor: 'var(--lb3)' }} />
          </radialGradient>
          <linearGradient id={`${u}r`} x1="0" y1="0" x2="0" y2="1">
            <stop offset=".55" style={{ stopColor: 'var(--lenny-rim)' }} stopOpacity="0" />
            <stop offset="1" style={{ stopColor: 'var(--lenny-rim)' }} stopOpacity=".8" />
          </linearGradient>
          <radialGradient id={`${u}e`} cx="38%" cy="30%" r="75%">
            <stop offset="0" stopColor="#34455E" />
            <stop offset="1" stopColor="#0B111C" />
          </radialGradient>
          <linearGradient id={`${u}l`} x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#3F9E45" />
            <stop offset="1" stopColor="#B9EE7E" />
          </linearGradient>
          <radialGradient id={`${u}m`} cx="50%" cy="25%" r="75%">
            <stop offset="0" stopColor="#6A2940" />
            <stop offset="1" stopColor="#26101A" />
          </radialGradient>
          <filter id={`${u}s`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="3.5" />
          </filter>
          <filter id={`${u}g`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="7" />
          </filter>
          <clipPath id={`${u}c`}>
            <path d={BODY} />
          </clipPath>
        </defs>
        <ellipse
          className="l-shadow"
          cx="0"
          cy="90"
          rx="62"
          ry="10"
          fill="rgba(16, 40, 28, .32)"
          filter={`url(#${u}s)`}
        />
        <g className="l-rig">
          <g className="l-body">
            <g className="l-sprout">
              <path
                d="M0,-78 C0,-90 3,-99 8,-107"
                stroke="#3E9E5F"
                strokeWidth="4.5"
                fill="none"
                strokeLinecap="round"
              />
              <path
                d="M8,-107 C20,-122 43,-117 45,-104 C32,-95 16,-97 8,-107Z"
                fill={`url(#${u}l)`}
              />
              <path
                d="M11,-106 C23,-109 33,-107 41,-105"
                stroke="#fff"
                strokeOpacity=".4"
                strokeWidth="1.4"
                fill="none"
                strokeLinecap="round"
              />
              <path
                d="M6,-102 C-6,-118 -29,-116 -31,-104 C-18,-95 -5,-96 6,-102Z"
                fill={`url(#${u}l)`}
              />
              <path
                d="M3,-102 C-9,-105 -19,-105 -27,-104"
                stroke="#fff"
                strokeOpacity=".4"
                strokeWidth="1.4"
                fill="none"
                strokeLinecap="round"
              />
            </g>
            <path d={BODY} fill={`url(#${u}b)`} />
            <g clipPath={`url(#${u}c)`}>
              <ellipse
                cx="52"
                cy="46"
                rx="64"
                ry="70"
                style={{ fill: 'var(--lshade)' }}
                opacity=".22"
                filter={`url(#${u}g)`}
              />
              <path d={BODY} fill={`url(#${u}r)`} />
              <ellipse
                className="l-bulge"
                cx="0"
                cy="34"
                rx="22"
                ry="14"
                style={{ fill: 'var(--lb3)' }}
              />
            </g>
            <ellipse
              cx="-38"
              cy="-44"
              rx="24"
              ry="13"
              fill="#fff"
              opacity=".55"
              transform="rotate(-32 -38 -44)"
              filter={`url(#${u}s)`}
            />
            <ellipse
              cx="-46"
              cy="-50"
              rx="6.5"
              ry="3.6"
              fill="#fff"
              opacity=".95"
              transform="rotate(-32 -46 -50)"
            />
            <ellipse
              cx="-50"
              cy="16"
              rx="13"
              ry="8"
              fill="#FF8AA5"
              opacity=".6"
              filter={`url(#${u}s)`}
            />
            <ellipse
              cx="50"
              cy="16"
              rx="13"
              ry="8"
              fill="#FF8AA5"
              opacity=".6"
              filter={`url(#${u}s)`}
            />
            <g className="l-face">
              <path
                className="l-brows"
                d="M-40,-31 L-16,-24 M16,-24 L40,-31"
                stroke="#101826"
                strokeWidth="4"
                strokeLinecap="round"
                fill="none"
              />
              <g className="l-eyes-open">
                <Eye cx={-27} u={u} />
                <Eye cx={27} u={u} />
              </g>
              <g className="l-eyes-happy">
                <Arc cx={-27} up />
                <Arc cx={27} up />
              </g>
              <g className="l-eyes-closed">
                <Arc cx={-27} up={false} />
                <Arc cx={27} up={false} />
              </g>
              <g className="l-mouth" transform="translate(0 20)">
                <path
                  className="l-frown"
                  d="M-10,5 Q0,-4 10,5"
                  stroke="#101826"
                  strokeWidth="4.2"
                  fill="none"
                  strokeLinecap="round"
                />
                <path
                  className="l-smile"
                  d="M-10,0 Q0,9.5 10,0"
                  stroke="#101826"
                  strokeWidth="4.2"
                  fill="none"
                  strokeLinecap="round"
                />
                <g className="l-open">
                  <ellipse rx="17" ry="15" fill={`url(#${u}m)`} />
                  <ellipse cy="8" rx="10" ry="5.5" fill="#FF7C93" />
                </g>
              </g>
            </g>
          </g>
        </g>
      </svg>
    )
  },
)
