import pandas as pd
import os
import re
import shutil
import io

class DialogueParser:
    def __init__(self, csv_path):
        self.csv_path = csv_path
        self.sections = self._parse_csv()

    def _parse_csv(self):
        sections = {}
        current_section = None
        buffer = []

        with open(self.csv_path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f]

        i = 5
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Detect Section Title (single-column line)
            if ',' not in line:
                if current_section and buffer:
                    section_csv = "\n".join(buffer)
                    df = pd.read_csv(io.StringIO(section_csv), header=0)
                    sections[current_section] = df
                    buffer = []

                current_section = line
                print(f'Current Section: {current_section}')
                i += 1  # Header line
                if i >= len(lines):
                    break
                header = lines[i].strip()
                i += 1  # Types line (skip explicitly!)
                i += 1  # Start data rows
                buffer = [header]  # ONLY header line; no types line
                continue

            # Add data lines to buffer
            if current_section:
                buffer.append(line)

            i += 1

        # Parse final section
        if current_section and buffer:
            section_csv = "\n".join(buffer)
            df = pd.read_csv(io.StringIO(section_csv), header=0)
            sections[current_section] = df

        return sections

    def get_section(self, name, drop_cols=None):
        #print(f'Sections: {self.sections}')
        df = self.sections.get(name, pd.DataFrame()).copy()
        if drop_cols:
            df = df.drop(columns=drop_cols, errors='ignore')
        #print(f'DF: {df}')
        return df

    def build_mermaid_graph(self, conv_id):
        entries_df = self.get_section('DialogueEntries')
        links_df = self.get_section('OutgoingLinks')

        entries_df[['ConvID', 'ID']] = entries_df[['ConvID', 'ID']].apply(pd.to_numeric, errors='coerce')
        links_df[['OriginConvID', 'OriginID', 'DestConvID', 'DestID']] = links_df[
            ['OriginConvID', 'OriginID', 'DestConvID', 'DestID']].apply(pd.to_numeric, errors='coerce')

        conv_entries = entries_df[entries_df.ConvID == conv_id]
        conv_links = links_df[links_df.OriginConvID == conv_id]

        graph = ["```mermaid\ngraph TD"]
        node_labels = {}

        for _, entry in conv_entries.iterrows():
            node_id = f"{int(entry.ConvID)}_{int(entry.ID)}"
            speaker = f"Actor_{entry.Actor}"
            dialogue = entry.DialogueText if pd.notna(entry.DialogueText) else ""
            dialogue = dialogue.replace('"', "'").replace("\n", " ")
            label = f"{speaker}: {dialogue}" if dialogue else speaker
            label = re.sub(r"[\[\]<>#|]", "", label)
            node_labels[node_id] = label
            graph.append(f'    {node_id}["{label}"]')

        for _, link in conv_links.iterrows():
            origin_id = f"{int(link.OriginConvID)}_{int(link.OriginID)}"
            dest_id = f"{int(link.DestConvID)}_{int(link.DestID)}"
            if origin_id in node_labels and dest_id in node_labels:
                graph.append(f"    {origin_id} --> {dest_id}")

        graph.append("```")
        return '\n'.join(graph)

    def build_all_dialogue_graphs(self, output_dir='docs/Dialogue'):
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        conversations_df = self.get_section('Conversations', drop_cols=['Overrides'])
        conversations_df['ID'] = pd.to_numeric(conversations_df['ID'], errors='coerce')

        for _, conv in conversations_df.iterrows():
            if pd.isna(conv['ID']):
                continue
            conv_id = int(conv['ID'])

            # Use the slashes to build nested folders
            conv_path_parts = conv['Title'].split('/')
            nested_dirs, file_name = conv_path_parts[:-1], conv_path_parts[-1]

            # Sanitize paths
            nested_dirs = [re.sub(r'[^a-zA-Z0-9]+', '_', part).strip('_') for part in nested_dirs]
            file_name = re.sub(r'[^a-zA-Z0-9]+', '_', file_name).strip('_') + '.md'

            # Create full nested directory path
            full_nested_path = os.path.join(output_dir, *nested_dirs)
            os.makedirs(full_nested_path, exist_ok=True)

            md_content = [f"# {conv['Title']}\n\n"]
            md_content.append(self.build_mermaid_graph(conv_id))

            md_path = os.path.join(full_nested_path, file_name)
            with open(md_path, 'w', encoding='utf-8') as f:
                f.writelines('\n'.join(md_content))

        return f"✅ Generated nested dialogue graphs in `{output_dir}`!"

# MkDocs macros integration
def define_env(env):
    @env.macro
    def parse_dialogue(csv_path):
        parser = DialogueParser(csv_path)
        return parser.sections

    @env.macro
    def build_dialogue_graphs(csv_path, output_dir='docs/Dialogue'):
        parser = DialogueParser(csv_path)
        return parser.build_all_dialogue_graphs(output_dir)


if __name__ == '__main__':
    parser = DialogueParser('docs/assets/dialogue/export_raw.csv')
    result = parser.build_all_dialogue_graphs('docs/Dialogue')
    print(result)