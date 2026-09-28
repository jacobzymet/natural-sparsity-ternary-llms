// Five-position presence-bit extractor for a byte-packed bitmap stream.
//
// The bitmap contains exactly one bit per weight position. Five positions are
// consumed per accepted cycle. A 16-bit {next,current} byte window is enough
// for every 3-bit intra-byte offset.
module bitcos_presence5_bytecursor (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       start_block,
    input  logic [2:0] initial_offset,
    input  logic       advance,
    input  logic [7:0] current_presence_byte,
    input  logic [7:0] next_presence_byte,
    output logic [4:0] presence,
    output logic [2:0] offset_state,
    output logic       advance_presence_byte
);
    logic [2:0] offset;
    logic [15:0] pair;
    logic [15:0] shifted;
    logic [3:0] offset_plus_five;

    assign pair = {next_presence_byte, current_presence_byte};
    assign shifted = pair >> offset;
    assign presence = shifted[4:0];

    always_comb begin
        offset_plus_five = {1'b0, offset} + 4'd5;
        advance_presence_byte = advance && offset_plus_five[3];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            offset <= '0;
        else if (start_block)
            offset <= initial_offset;
        else if (advance)
            offset <= offset_plus_five[2:0];
    end

    assign offset_state = offset;
endmodule
