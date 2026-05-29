// web/src/components/DevicesPanel.tsx
import { h } from 'preact'
import { useEffect } from 'preact/hooks'
import { devices, fetchDevices, approveDevice, rejectDevice, removeDevice, lastIssuedToken, approvingDeviceId } from '../signals'

export function DevicesPanel() {
  useEffect(() => {
    void fetchDevices()
    return () => { lastIssuedToken.value = null }
  }, [])
  const list = devices.value
  if (list.length === 0) {
    return (
      <p data-devices-empty="true" style={{
        fontFamily: 'var(--font)', color: 'var(--md-sys-color-on-surface-variant)', padding: '12px 0',
      }}>
        No devices yet. A phone or sensor on your Wi-Fi can request to join here.
      </p>
    )
  }
  const token = lastIssuedToken.value
  return (
    <ul data-devices-panel="true" style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {list.map((d) => (
        <li key={d.device_id} data-device-row={d.device_id} style={{
          padding: '12px 16px', borderRadius: 'var(--md-sys-shape-corner-medium)',
          background: 'var(--md-sys-color-surface-container-low)', fontFamily: 'var(--font)',
          display: 'flex', flexDirection: 'column', gap: '8px',
        }}>
          <span style={{ color: 'var(--md-sys-color-on-surface)' }}>
            {d.name} · <span data-device-status={d.status} style={{ color: 'var(--md-sys-color-on-surface-variant)' }}>
              {d.role} · {d.status}
            </span>
          </span>
          {token && token.device_id === d.device_id && (
            <code data-token-reveal role="status" style={{
              fontSize: 'var(--md-sys-typescale-label-medium-size)',
              background: 'var(--md-sys-color-surface-container-highest)',
              padding: '6px 8px', borderRadius: 'var(--md-sys-shape-corner-small)', wordBreak: 'break-all',
            }}>
              Save this token on the device (shown once): {token.token}
            </code>
          )}
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {d.status === 'pending' && (
              <button type="button" data-approve={d.device_id}
                aria-label={`Approve ${d.name}`}
                disabled={approvingDeviceId.value === d.device_id}
                onClick={() => approveDevice(d.device_id)}
                style={pillStyle('var(--md-sys-color-primary)', 'var(--md-sys-color-on-primary)')}>Approve</button>
            )}
            {d.status === 'pending' && (
              <button type="button" data-reject={d.device_id}
                aria-label={`Reject ${d.name}`}
                onClick={() => rejectDevice(d.device_id)}
                style={pillStyle('transparent', 'var(--md-sys-color-on-surface-variant)')}>Reject</button>
            )}
            <button type="button" data-remove={d.device_id}
              aria-label={`Remove ${d.name}`}
              onClick={() => removeDevice(d.device_id)}
              style={pillStyle('transparent', 'var(--md-sys-color-error)')}>Remove</button>
          </span>
        </li>
      ))}
    </ul>
  )
}

function pillStyle(bg: string, color: string): h.JSX.CSSProperties {
  return {
    minHeight: '36px', padding: '4px 14px', borderRadius: 'var(--md-sys-shape-corner-full)',
    background: bg, color, border: bg === 'transparent' ? '1px solid var(--md-sys-color-outline-variant)' : 'none',
    fontFamily: 'var(--font)', fontSize: 'var(--md-sys-typescale-label-medium-size)', cursor: 'pointer',
  }
}
