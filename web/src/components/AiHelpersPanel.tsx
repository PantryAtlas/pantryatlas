import { h } from 'preact'
import { useEffect, useState } from 'preact/hooks'

type Provider = {
  name: string
  kind: string
  capabilities: string[]
  priority: number
  enabled: boolean
  available: boolean
}

export function AiHelpersPanel() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [multimodal, setMultimodal] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    const r = await fetch('/navigator/providers')
    setProviders(await r.json())
  }

  useEffect(() => {
    refresh()
  }, [])

  async function addProvider(e: h.JSX.TargetedEvent<HTMLFormElement, Event>) {
    e.preventDefault()
    setError(null)
    const r = await fetch('/navigator/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, base_url: baseUrl, multimodal }),
    })
    if (!r.ok) {
      const data = await r.json()
      setError(data.detail ?? 'Could not add helper')
      return
    }
    setName('')
    setBaseUrl('')
    setMultimodal(false)
    refresh()
  }

  async function testProvider(n: string) {
    await fetch(`/navigator/providers/${encodeURIComponent(n)}/test`, { method: 'POST' })
    refresh()
  }

  async function removeProvider(n: string) {
    await fetch(`/navigator/providers/${encodeURIComponent(n)}`, { method: 'DELETE' })
    refresh()
  }

  return (
    <section
      style={{
        marginTop: '32px',
        padding: '24px 20px',
        borderRadius: 'var(--md-sys-shape-corner-extra-large)',
        background: 'var(--md-sys-color-surface-container)',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}
    >
      <div>
        <h2
          style={{
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-title-medium-size)',
            fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
            lineHeight: 'var(--md-sys-typescale-title-medium-line-height)',
            color: 'var(--md-sys-color-on-surface)',
            margin: '0 0 6px',
          }}
        >
          AI helpers on your network
        </h2>
        <p
          style={{
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-medium-size)',
            color: 'var(--md-sys-color-on-surface-variant)',
            margin: '0',
          }}
        >
          Point PantryAtlas at a more powerful computer on your home network to do
          the heavy lifting. Nothing leaves your network.
        </p>
      </div>

      <ul
        role="list"
        style={{
          listStyle: 'none',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          margin: '0',
          padding: '0',
        }}
      >
        {providers.map((p) => (
          <li
            key={p.name}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              padding: '12px 16px',
              borderRadius: 'var(--md-sys-shape-corner-large)',
              background: 'var(--md-sys-color-surface-container-high)',
              flexWrap: 'wrap',
            }}
          >
            {/* Status dot */}
            <span
              aria-hidden="true"
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                flexShrink: 0,
                background: p.available
                  ? 'var(--md-sys-color-tertiary)'
                  : 'var(--md-sys-color-error)',
              }}
            />
            <strong
              style={{
                fontFamily: 'var(--font)',
                fontSize: 'var(--md-sys-typescale-body-large-size)',
                fontWeight: 'var(--md-sys-typescale-title-medium-weight)',
                color: 'var(--md-sys-color-on-surface)',
              }}
            >
              {p.name}
            </strong>
            <span
              style={{
                fontFamily: 'var(--font)',
                fontSize: 'var(--md-sys-typescale-body-small-size)',
                color: 'var(--md-sys-color-on-surface-variant)',
                flex: 1,
              }}
            >
              {p.kind} · {p.capabilities.join(', ')} · priority {p.priority}
            </span>
            <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
              <button
                type="button"
                onClick={() => testProvider(p.name)}
                style={{
                  padding: '6px 14px',
                  borderRadius: 'var(--md-sys-shape-corner-full)',
                  background: 'var(--md-sys-color-secondary-container)',
                  color: 'var(--md-sys-color-on-secondary-container)',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'var(--font)',
                  fontSize: 'var(--md-sys-typescale-label-medium-size)',
                  fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                  minHeight: '36px',
                }}
              >
                Test
              </button>
              {p.kind !== 'local' && (
                <button
                  type="button"
                  onClick={() => removeProvider(p.name)}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 'var(--md-sys-shape-corner-full)',
                    background: 'transparent',
                    color: 'var(--md-sys-color-error)',
                    border: '1px solid var(--md-sys-color-error)',
                    cursor: 'pointer',
                    fontFamily: 'var(--font)',
                    fontSize: 'var(--md-sys-typescale-label-medium-size)',
                    fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
                    minHeight: '36px',
                  }}
                >
                  Remove
                </button>
              )}
            </div>
          </li>
        ))}
        {providers.length === 0 && (
          <li
            style={{
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-body-medium-size)',
              color: 'var(--md-sys-color-on-surface-variant)',
              padding: '8px 0',
            }}
          >
            No helpers configured yet.
          </li>
        )}
      </ul>

      {/* Add helper form */}
      <form
        onSubmit={addProvider}
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
          paddingTop: '8px',
          borderTop: '1px solid var(--md-sys-color-outline-variant)',
        }}
      >
        <p
          style={{
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-label-medium-size)',
            fontWeight: 'var(--md-sys-typescale-label-medium-weight)',
            color: 'var(--md-sys-color-on-surface-variant)',
            margin: '0',
          }}
        >
          Add a helper
        </p>
        <input
          type="text"
          placeholder="Name (e.g. kitchen-desktop)"
          value={name}
          onInput={(e) => setName((e.target as HTMLInputElement).value)}
          required
          style={{
            height: '48px',
            padding: '0 16px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'var(--md-sys-color-surface-container-high)',
            border: '1.5px solid var(--md-sys-color-outline-variant)',
            outline: 'none',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-large-size)',
            color: 'var(--md-sys-color-on-surface)',
          }}
        />
        <input
          type="text"
          placeholder="http://192.168.1.50:8080"
          value={baseUrl}
          onInput={(e) => setBaseUrl((e.target as HTMLInputElement).value)}
          required
          style={{
            height: '48px',
            padding: '0 16px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'var(--md-sys-color-surface-container-high)',
            border: '1.5px solid var(--md-sys-color-outline-variant)',
            outline: 'none',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-large-size)',
            color: 'var(--md-sys-color-on-surface)',
          }}
        />
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-body-medium-size)',
            color: 'var(--md-sys-color-on-surface)',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={multimodal}
            onChange={(e) => setMultimodal((e.target as HTMLInputElement).checked)}
            style={{ width: '18px', height: '18px', cursor: 'pointer' }}
          />
          This helper can see photos (multimodal)
        </label>
        <button
          type="submit"
          style={{
            height: '48px',
            padding: '0 24px',
            borderRadius: 'var(--md-sys-shape-corner-full)',
            background: 'var(--md-sys-color-primary)',
            color: 'var(--md-sys-color-on-primary)',
            border: 'none',
            cursor: 'pointer',
            fontFamily: 'var(--font)',
            fontSize: 'var(--md-sys-typescale-label-large-size)',
            fontWeight: 'var(--md-sys-typescale-label-large-weight)',
            alignSelf: 'flex-start',
          }}
        >
          Add helper
        </button>
        {error && (
          <p
            role="alert"
            style={{
              margin: '0',
              padding: '8px 14px',
              borderRadius: 'var(--md-sys-shape-corner-medium)',
              background: 'var(--md-sys-color-error-container)',
              color: 'var(--md-sys-color-error)',
              fontFamily: 'var(--font)',
              fontSize: 'var(--md-sys-typescale-body-medium-size)',
            }}
          >
            {error}
          </p>
        )}
      </form>
    </section>
  )
}
