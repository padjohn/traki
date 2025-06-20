import pandas as pd
import os
import re
import shutil
import io
import json

class DialogueParser:
    def __init__(self, csv_path):
        self.csv_path = csv_path
        self.sections = self._parse_csv()

    def _parse_csv(self):
        sections = {}
        current_section = None
        buffer = []

        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"CSV file not found at: {self.csv_path}")

        with open(self.csv_path, encoding='utf-8') as f:
            lines = [line.rstrip('\n') for line in f]

        i = 5
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if ',' not in line:
                if current_section and buffer:
                    section_csv = "\n".join(buffer)
                    df = pd.read_csv(io.StringIO(section_csv), header=0)
                    sections[current_section] = df
                    buffer = []

                current_section = line
                i += 1
                if i >= len(lines):
                    break
                header = lines[i].strip()
                i += 2
                buffer = [header]
                continue

            if current_section:
                buffer.append(line)

            i += 1

        if current_section and buffer:
            section_csv = "\n".join(buffer)
            df = pd.read_csv(io.StringIO(section_csv), header=0)
            sections[current_section] = df

        return sections

    def get_section(self, name, drop_cols=None):
        df = self.sections.get(name, pd.DataFrame()).copy()
        if drop_cols:
            df = df.drop(columns=drop_cols, errors='ignore')
        return df

    def _escape_markdown_special_chars(self, text):
        """
        Escapes common Markdown special characters to ensure literal interpretation.
        This includes characters that might be interpreted as formatting, links,
        or path separators.
        """
        if not isinstance(text, str):
            return text
        
        text = text.replace('\\', '\\\\')
        special_chars = r'`*_{}[]()#+-.!>/'
        for char in special_chars:
            if char != '\\':
                text = text.replace(char, '\\' + char)
        return text

    def build_dialogue_table_markdown(self, conv_id):
        entries_df = self.get_section('DialogueEntries')
        links_df = self.get_section('OutgoingLinks')

        entries_df[['ConvID', 'ID']] = entries_df[['ConvID', 'ID']].apply(pd.to_numeric, errors='coerce')
        links_df[['OriginConvID', 'OriginID', 'DestConvID', 'DestID']] = links_df[
            ['OriginConvID', 'OriginID', 'DestConvID', 'DestID']].apply(pd.to_numeric, errors='coerce')

        conv_entries = entries_df[entries_df.ConvID == conv_id].copy()
        conv_links = links_df[links_df.OriginConvID == conv_id].copy()

        # --- Filter out truly orphaned nodes (reachable from Entry ID 0 using BFS) ---
        reachable_ids = set()
        bfs_queue = []

        if 0 in conv_entries['ID'].values:
            bfs_queue.append(0)
            reachable_ids.add(0)
        
        while bfs_queue:
            current_id = bfs_queue.pop(0) 
            current_entry_links = conv_links[conv_links.OriginID == current_id]
            for _, link in current_entry_links.iterrows():
                dest_id = int(link.DestID)
                if dest_id in conv_entries['ID'].values and dest_id not in reachable_ids:
                    reachable_ids.add(dest_id)
                    bfs_queue.append(dest_id)
        
        # Filter oprhaned entries
        conv_entries = conv_entries[conv_entries.ID.isin(reachable_ids)].copy()
        
        # --- Depth-First Traversal (DFS) to determine display order ---
        ordered_entry_ids = []
        dfs_stack = []
        visited_dfs = set()

        if 0 in reachable_ids:
            dfs_stack.append(0)
            visited_dfs.add(0) 

        while dfs_stack:
            current_id = dfs_stack.pop()
            ordered_entry_ids.append(current_id)

            next_dest_ids = sorted([
                int(link.DestID) for _, link in conv_links[conv_links.OriginID == current_id].iterrows()
                if int(link.DestID) in reachable_ids and int(link.DestID) not in visited_dfs
            ], reverse=True) 

            for dest_id in next_dest_ids:
                if dest_id not in visited_dfs:
                    visited_dfs.add(dest_id)
                    dfs_stack.append(dest_id)
        
        final_ordered_ids = [id_ for id_ in ordered_entry_ids if id_ in conv_entries['ID'].values]
        conv_entries = conv_entries.set_index('ID').loc[final_ordered_ids].reset_index()
        conv_entries['Next Scene(s)'] = ''

        for idx, entry in conv_entries.iterrows():
            origin_id = entry.ID
            current_entry_links = conv_links[conv_links.OriginID == origin_id]

            next_scenes = []
            for _, link in current_entry_links.iterrows():
                dest_id = int(link.DestID)
                if dest_id not in reachable_ids: 
                    continue 
                    
                dest_entry = entries_df[(entries_df.ConvID == link.DestConvID) & (entries_df.ID == link.DestID)].iloc[0]
                dest_actor = dest_entry.entrytag.split('_')[0] if pd.notna(dest_entry.entrytag) else f"Actor_{dest_entry.Actor}"
                dest_dialogue = dest_entry.DialogueText if pd.notna(dest_entry.DialogueText) else ""
                dest_dialogue_clean = re.sub(r"\[.*?\]", "", dest_dialogue).strip().replace('"', "'").replace("\n", " ")
                
                inner_label_content = f"{dest_actor}: {dest_dialogue_clean[:50]}..." if len(dest_dialogue_clean) > 50 else f"{dest_actor}: {dest_dialogue_clean}"
                if not dest_dialogue_clean:
                    inner_label_content = dest_actor
                full_descriptive_label_string = f"[{inner_label_content}]"
                target_label_display = self._escape_markdown_special_chars(full_descriptive_label_string)

                next_scenes.append(f"➡️ `{int(link.DestID)}` {target_label_display}")

            if next_scenes:
                conv_entries.loc[idx, 'Next Scene(s)'] = '<br>'.join(next_scenes)
            else:
                conv_entries.loc[idx, 'Next Scene(s)'] = 'End'

        markdown_table = ""
        markdown_table += "| Entry ID | Speaker | Dialogue | Next |\n"
        markdown_table += "| :------- | :------ | :------- | :------------ |\n"

        for _, entry in conv_entries.iterrows():
            entry_id = f"`{int(entry.ID)}`"
            actor_name = entry.entrytag.split('_')[0] if pd.notna(entry.entrytag) else f"Actor_{entry.Actor}"
            
            dialogue_text = entry.DialogueText if pd.notna(entry.DialogueText) else ""
            dialogue_text = re.sub(r"\[.*?\]", "", dialogue_text).strip().replace('"', "'").replace("\n", " ")
            dialogue_text = self._escape_markdown_special_chars(dialogue_text)
            
            next_scenes_col = entry['Next Scene(s)']

            markdown_table += (
                f"| {entry_id} "
                f"| **{actor_name}** "
                f"| {dialogue_text} "
                f"| {next_scenes_col} |\n"
            )
        return markdown_table

    def build_all_dialogue_tables(self, output_dir='docs/Dialogue', exclude_conv_ids=None):
        if exclude_conv_ids is None:
            exclude_conv_ids = []
            
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        conversations_df = self.get_section('Conversations', drop_cols=['Overrides'])
        conversations_df['ID'] = pd.to_numeric(conversations_df['ID'], errors='coerce')

        for _, conv in conversations_df.iterrows():
            if pd.isna(conv['ID']):
                continue
            
            conv_id = int(conv['ID'])
            if conv_id in exclude_conv_ids:
                print(f"Skipping blacklisted conversation ID: {conv_id} - {conv.Title}")
                continue
            
            conv_path_parts = conv['Title'].split('/')
            nested_dirs = []
            for part in conv_path_parts[:-1]:
                sanitized_part = re.sub(r'[\\/:*?"<>|]+', ' ', part)
                sanitized_part = re.sub(r'[^a-zA-Z0-9 ]+', ' ', sanitized_part)
                sanitized_part = re.sub(r'\s+', ' ', sanitized_part).strip()
                if not sanitized_part: 
                    sanitized_part = "untitled_directory" 
                nested_dirs.append(sanitized_part)

            file_title_raw = conv_path_parts[-1] 
            sanitized_title = re.sub(r'[\\/:*?"<>|]+', ' ', file_title_raw)
            sanitized_title = re.sub(r'[^a-zA-Z0-9 ]+', ' ', sanitized_title)
            file_name_base = re.sub(r'\s+', ' ', sanitized_title).strip()
            
            if not file_name_base:
                file_name_base = "untitled_dialogue" 

            file_name = file_name_base + '.md'
            
            full_nested_path = os.path.join(output_dir, *nested_dirs)
            os.makedirs(full_nested_path, exist_ok=True)

            title_raw = conv_path_parts[-1]
            title_str = f"{title_raw}(D)" if title_raw.isnumeric() else title_raw

            md_content = [
                f"---\ntitle: {title_str}\n---\n",
                f"# {title_str}\n\n",
                self.build_dialogue_table_markdown(conv_id)
            ]

            md_path = os.path.join(full_nested_path, file_name)
            with open(md_path, 'w', encoding='utf-8') as f:
                f.writelines('\n'.join(md_content))

        return f"✅ Generated Markdown dialogue tables in `{output_dir}`"

def define_env(env):
    """
    This function is called by the mkdocs-macros-plugin.
    It registers the build_dialogue_tables function as a macro.
    """
    @env.macro
    def build_dialogue_tables(csv_path, output_dir='docs/Dialogue', exclude_conv_ids=None):
        parser = DialogueParser(csv_path)
        return parser.build_all_dialogue_tables(output_dir, exclude_conv_ids if exclude_conv_ids is not None else [])

# CLI entry point (for direct execution)
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate dialogue tables as Markdown pages.')
    parser.add_argument('--csv_path', default='docs/assets/dialogue/export_raw.csv', help='Path to the exported dialogue CSV')
    parser.add_argument('--output_dir', default='docs/Dialogue', help='Output directory for Markdown files')
    parser.add_argument('--exclude_conv_ids', nargs='*', type=int, default=[], 
                        help='List of Conversation IDs to exclude completely (e.g., --exclude_conv_ids 1 5 10)')
    args = parser.parse_args()

    dialogue_parser = DialogueParser(args.csv_path)
    result = dialogue_parser.build_all_dialogue_tables(args.output_dir, args.exclude_conv_ids)
    print(result)