import {
  ActionIcon,
  Anchor,
  AppShell,
  Burger,
  Group,
  Menu,
  NavLink,
  Select,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconArchive,
  IconBarcode,
  IconFileSpreadsheet,
  IconHistory,
  IconKey,
  IconLogout,
  IconMoon,
  IconPencil,
  IconPrinter,
  IconSettings,
  IconSun,
  IconUser,
} from '@tabler/icons-react'
import { NavLink as RouterLink, Outlet, useLocation } from 'react-router'

import { useMe } from '../api/hooks'
import { useSelectedPrinter } from './printerContext'
import { PrinterStatusBadge } from './PrinterStatusBadge'

const NAV = [
  { to: '/', label: 'Print ZPL', icon: IconPrinter, end: true },
  { to: '/designer', label: 'Designer', icon: IconPencil },
  { to: '/labels', label: 'Labels archive', icon: IconArchive },
  { to: '/templates', label: 'Print from template', icon: IconFileSpreadsheet },
  { to: '/history', label: 'Print history', icon: IconHistory },
  { to: '/printers', label: 'Printers', icon: IconSettings },
  { to: '/integrations', label: 'API access', icon: IconKey },
]

function PrinterPicker() {
  const { printers, printer, setPrinterId } = useSelectedPrinter()
  if (printers.length === 0) {
    return (
      <Anchor component={RouterLink} to="/printers" size="sm">
        Add a printer
      </Anchor>
    )
  }
  return (
    <Group gap="xs" wrap="nowrap">
      <Select
        aria-label="Printer"
        size="xs"
        w={200}
        allowDeselect={false}
        data={printers.map((p) => ({ value: String(p.id), label: p.name }))}
        value={printer ? String(printer.id) : null}
        onChange={(value) => setPrinterId(value ? Number(value) : null)}
      />
      <PrinterStatusBadge printerId={printer?.id} />
    </Group>
  )
}

function UserMenu() {
  const { data: me } = useMe()
  if (!me?.auth_enabled) return null
  return (
    <Menu position="bottom-end">
      <Menu.Target>
        <ActionIcon variant="default" aria-label="User menu">
          <IconUser size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{me.name ?? me.email ?? me.sub}</Menu.Label>
        <Menu.Item component="a" href="/auth/logout" leftSection={<IconLogout size={14} />}>
          Log out
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const { colorScheme, toggleColorScheme } = useMantineColorScheme()
  const location = useLocation()

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 230, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <IconBarcode size={26} />
            <Title order={4} visibleFrom="xs">
              Zebra Web
            </Title>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <PrinterPicker />
            <ActionIcon
              variant="default"
              onClick={toggleColorScheme}
              aria-label="Toggle color scheme"
            >
              {colorScheme === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
            </ActionIcon>
            <UserMenu />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            component={RouterLink}
            to={to}
            end={end}
            label={label}
            leftSection={<Icon size={18} />}
            active={end ? location.pathname === to : location.pathname.startsWith(to)}
            onClick={close}
          />
        ))}
        <Text size="xs" c="dimmed" mt="auto" p="xs">
          Local ZPL preview renderer · previews are approximations
        </Text>
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
