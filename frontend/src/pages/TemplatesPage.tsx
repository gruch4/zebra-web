import {
  AspectRatio,
  Badge,
  Card,
  Center,
  Group,
  Image,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconSearch } from '@tabler/icons-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { useLabels } from '../api/hooks'

export function TemplatesPage() {
  const [search, setSearch] = useState('')
  const [q] = useDebouncedValue(search, 300)
  const { data, isLoading } = useLabels({ q, has_variables: true, limit: 200 })

  return (
    <Stack>
      <Title order={2}>Print from template</Title>
      <Text c="dimmed">
        Pick a label that contains template variables. Fill the values for a single label, or upload
        a CSV, JSON, YAML or Excel file to print one label per row.
      </Text>
      <TextInput
        placeholder="Search templates"
        leftSection={<IconSearch size={16} />}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        w={300}
      />
      {!isLoading && data?.items.length === 0 && (
        <Text c="dimmed" ta="center" py="xl">
          No templates yet. Add {'{{variables}}'} to a label in the designer or the ZPL editor and
          save it to the archive.
        </Text>
      )}
      <SimpleGrid cols={{ base: 1, xs: 2, md: 3, xl: 4 }}>
        {data?.items.map((label) => (
          <Card
            key={label.id}
            withBorder
            padding="sm"
            component={Link}
            to={`/templates/${label.id}`}
          >
            <Card.Section>
              <AspectRatio ratio={3 / 2} bg="var(--mantine-color-gray-light)">
                <Center p="xs">
                  <Image
                    src={`/api/labels/${label.id}/preview.png?v=${encodeURIComponent(label.updated_at)}`}
                    alt={`Preview of ${label.name}`}
                    fit="contain"
                    mah="100%"
                    bg="white"
                  />
                </Center>
              </AspectRatio>
            </Card.Section>
            <Text fw={600} mt="sm" truncate>
              {label.name}
            </Text>
            <Group gap={4} mt={4}>
              {label.variables.map((v) => (
                <Badge key={v.name} size="xs" variant="light" color="teal">
                  {v.label || v.name}
                </Badge>
              ))}
            </Group>
          </Card>
        ))}
      </SimpleGrid>
    </Stack>
  )
}
